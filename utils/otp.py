"""One-time codes sent by e-mail.

Two flows use them: proving you own an address before an account is created
for it (signup), and the forgotten-password flow. A code is bound to what it
was issued for (`purpose`) and to whom (`subject`), so a code mailed for one
can never be spent on the other.

Guessing is capped per code in the database (`MAX_ATTEMPTS`), on top of the
rate limiter — the limiter's default storage is per process, so with several
gunicorn workers it alone would multiply the guesses an attacker gets.
"""

import secrets
from datetime import datetime, timedelta, timezone

from extentions.db import db
from models.otpModel import Otp, PURPOSE_SIGNUP_NOTICE

CODE_LENGTH = 6
TTL_MINUTES = 5
MAX_ATTEMPTS = 5
# A new code is not issued while the previous one is younger than this, so a
# stream of requests cannot flood somebody's inbox. The UI waits it out too.
RESEND_COOLDOWN_SECONDS = 60


def generate_code(length=CODE_LENGTH):
    # `secrets`, not `random`: the code is a credential and must not be predictable.
    return ''.join(str(secrets.randbelow(10)) for _ in range(length))


def _now():
    return datetime.now(timezone.utc)


def _aware(value):
    """Postgres returns tz-aware timestamps; SQLite (tests) returns naive UTC."""
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _codes_for(subject, purpose):
    return Otp.query.filter_by(fin_kod=subject, purpose=purpose)


def discard_codes(subject, purpose):
    _codes_for(subject, purpose).delete(synchronize_session=False)


def issue_code(subject, purpose):
    """A fresh code for `subject`, committed, or None while the previous code is
    still inside the resend cooldown. Only the newest code is ever valid."""
    now = _now()
    latest = _codes_for(subject, purpose).order_by(Otp.issued_at.desc()).first()
    if latest and now - _aware(latest.issued_at) < timedelta(seconds=RESEND_COOLDOWN_SECONDS):
        return None

    # Housekeeping: expired codes (e.g. abandoned signups) are never read again.
    Otp.query.filter(Otp.expires_at < now).delete(synchronize_session=False)
    discard_codes(subject, purpose)

    code = generate_code()
    row = Otp(
        fin_kod=subject,
        purpose=purpose,
        attempts=0,
        issued_at=now,
        expires_at=now + timedelta(minutes=TTL_MINUTES),
    )
    row.set_code(code)
    db.session.add(row)
    db.session.commit()
    return code


def notice_allowed(subject):
    """True when an "address already has an account" notice may be mailed to
    `subject` now. Recorded like a code (one that is never sent or accepted),
    so a notice obeys the same cooldown as a code, and the two branches of
    signup step 1 do the same database work."""
    return issue_code(subject, PURPOSE_SIGNUP_NOTICE) is not None


def consume_code(subject, purpose, code):
    """True when `code` is the live code for `subject` and `purpose`.

    Call it before staging any other change in the session: the failure paths
    commit. On success the code's deletion is only STAGED: the caller commits it
    together with whatever the code unlocks (e.g. the new account), so a failure
    there rolls back and the code stays usable. On failure the attempt count is
    committed here, and the code is destroyed once it reaches MAX_ATTEMPTS.
    """
    code = str(code if code is not None else '').strip()
    # Row lock: concurrent guesses are counted one after another, never in
    # parallel past the cap. (SQLite ignores FOR UPDATE; Postgres honours it.)
    row = (
        _codes_for(subject, purpose)
        .order_by(Otp.issued_at.desc())
        .with_for_update()
        .first()
    )
    if row is None:
        return False

    if _now() > _aware(row.expires_at) or (row.attempts or 0) >= MAX_ATTEMPTS:
        discard_codes(subject, purpose)
        db.session.commit()
        return False

    if not (len(code) == CODE_LENGTH and code.isdigit() and row.matches(code)):
        row.attempts = (row.attempts or 0) + 1
        if row.attempts >= MAX_ATTEMPTS:
            discard_codes(subject, purpose)
        db.session.commit()
        return False

    discard_codes(subject, purpose)
    return True
