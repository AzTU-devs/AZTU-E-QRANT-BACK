import hashlib
import hmac

from flask import current_app

from extentions.db import db

# What a code was issued for. A code is only ever accepted for the purpose it
# was mailed for, so a signup code can never be spent to reset a password.
PURPOSE_SIGNUP = 'signup'
PURPOSE_PASSWORD_RESET = 'password_reset'
# Marks that an "address already has an account" notice was mailed, so notices
# share the codes' resend cooldown. Such a row's code is never sent and no
# endpoint accepts this purpose.
PURPOSE_SIGNUP_NOTICE = 'signup_notice'


class Otp(db.Model):
    __tablename__ = 'otp'

    id = db.Column(db.Integer, primary_key=True)
    # Legacy plaintext column, kept nullable for old rows. New codes are NOT
    # stored here — only their keyed hash goes in `otp_hash` (finding B-L4).
    otp = db.Column(db.Integer, nullable=True)
    otp_hash = db.Column(db.String(64))
    # Whom the code was mailed to: the account key for a password reset, the
    # e-mail address being verified for a signup (no account exists yet).
    fin_kod = db.Column(db.String, nullable=False)
    purpose = db.Column(db.String(20))
    # Wrong guesses against this code. Counted in the database so the cap holds
    # across every worker process, unlike the in-memory rate limiter.
    attempts = db.Column(db.Integer, nullable=False, default=0)
    issued_at = db.Column(db.DateTime(timezone=True), nullable=False)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)

    def _digest(self, code):
        """HMAC of the code, keyed with SECRET_KEY and bound to its purpose and
        recipient. A plain SHA-256 of a 6-digit code is reversed by trying all
        million values; without the key a leaked table reveals nothing."""
        key = current_app.config['SECRET_KEY'].encode('utf-8')
        message = f'{self.purpose}|{self.fin_kod}|{code}'.encode('utf-8')
        return hmac.new(key, message, hashlib.sha256).hexdigest()

    def set_code(self, code):
        """Store only the keyed hash of the one-time code, never the code itself."""
        self.otp_hash = self._digest(str(code))

    def matches(self, code):
        """Constant-time comparison against the stored hash."""
        if not self.otp_hash or not self.purpose:
            return False
        return hmac.compare_digest(self.otp_hash, self._digest(str(code)))
