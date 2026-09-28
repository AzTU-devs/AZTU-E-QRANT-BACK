"""Accounts are reached by e-mail address.

Everything a person types to get into the system — signing up, signing in,
the forgotten-password flow — is their e-mail address; a FIN code is never
accepted as an identifier.

Every account has an internal key, `Auth.fin_kod`, which the rest of the schema
references (tokens, foreign keys). For accounts created before e-mail signup it
is the person's FIN code. Accounts registered since then — and experts — are
keyed by the address they verified, so no FIN is collected at all.

A person's address lives on their profile (`User.personal_email`, verified by
OTP at registration and not editable afterwards, and `User.work_email`).
Experts have no profile row: their `Auth` row is keyed by their address
directly. Addresses are compared case-insensitively, and every write that sets
one is checked with `email_taken`, so one address can never resolve to two
accounts.
"""

import re
import logging

from sqlalchemy import func, or_

from models.authModel import Auth
from models.userModel import User
from models.expertModel import Expert, EXPERT_ROLE
from utils.email_validation import normalise_email, has_valid_syntax

logger = logging.getLogger(__name__)

MAX_NAME_LENGTH = 100
# Letters of any alphabet (ə, ğ, ı, ö, ü, ç, ş ...), joined by single spaces,
# hyphens, apostrophes or dots. Rejects anything that could form markup.
NAME_PATTERN = re.compile(r"^[^\W\d_]+(?:[ '’ʼ.\-]+[^\W\d_]+)*\.?$")


def clean_person_name(value):
    """(tidied name, problem) for a first name, surname or father's name.
    Names are shown across the admin screens, so only letters and ordinary
    separators are stored."""
    name = ' '.join(value.split()) if isinstance(value, str) else ''
    if not name:
        return name, "Ad, soyad və ata adı tələb olunur."
    if len(name) > MAX_NAME_LENGTH or not NAME_PATTERN.match(name):
        return name, "Ad, soyad və ata adı yalnız hərflərdən ibarət olmalıdır."
    return name, None


def users_with_email(email):
    email = normalise_email(email)
    if not email:
        return []
    return User.query.filter(or_(
        func.lower(User.personal_email) == email,
        func.lower(User.work_email) == email,
    )).all()


def resolve_account_by_email(identifier):
    """The `Auth` row a sign-in address belongs to, or None.

    None also when the address is ambiguous (held by two different people) —
    refusing is safer than guessing which account to open.
    """
    email = normalise_email(identifier)
    if not has_valid_syntax(email):
        return None

    fins = {u.fin_kod for u in users_with_email(email)}
    if len(fins) > 1:
        logger.error("E-mail address is shared by %d profiles; sign-in refused until an admin fixes it", len(fins))
        return None
    if len(fins) == 1:
        return Auth.query.filter_by(fin_kod=fins.pop()).first()

    account = Auth.query.filter(func.lower(Auth.fin_kod) == email).first()
    if account and account.project_role == EXPERT_ROLE:
        return account
    return None


def resolve_profile(identifier):
    """(User, Auth) for an e-mail address, or (None, None) — used by the
    forgotten-password flow. Only an address is accepted, never a FIN code."""
    email = normalise_email(identifier)
    if not has_valid_syntax(email):
        return None, None
    users = users_with_email(email)
    if len({u.fin_kod for u in users}) != 1:
        return None, None
    user = users[0]
    return user, Auth.query.filter_by(fin_kod=user.fin_kod).first()


def email_taken(email, exclude_fin=None):
    """True when the address already signs somebody else in — or is reserved
    for an expert. An expert record gets its login (an `Auth` row keyed by the
    address) only on first appointment; if the address could be self-registered
    before that, the appointment would land on the registrant's own account."""
    email = normalise_email(email)
    if not email:
        return False
    if any(u.fin_kod != exclude_fin for u in users_with_email(email)):
        return True
    expert = Expert.query.filter(func.lower(Expert.email) == email).first()
    if expert is not None and expert.email != exclude_fin:
        return True
    account = Auth.query.filter(func.lower(Auth.fin_kod) == email).first()
    return account is not None and account.fin_kod != exclude_fin
