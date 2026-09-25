"""Signing in by e-mail address.

People sign in with their e-mail address, not their FIN code. The FIN stays the
account's INTERNAL identity (tokens, foreign keys, admin screens) — it is simply
no longer the thing typed on the sign-in form.

A person's address lives on their profile (`User.personal_email`, set at
registration, and `User.work_email`). Experts have no profile row: their `Auth`
row is keyed by their address directly. Addresses are compared
case-insensitively, and every write that sets one is checked with
`email_taken`, so one address can never resolve to two accounts.
"""

import logging

from sqlalchemy import func, or_

from models.authModel import Auth
from models.userModel import User
from models.expertModel import EXPERT_ROLE
from utils.email_validation import normalise_email, has_valid_syntax

logger = logging.getLogger(__name__)


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
    """(User, Auth) for an e-mail address or a FIN code — used by the
    forgotten-password flow, which needs the profile to know where to mail."""
    identifier = (identifier or '').strip()
    if '@' in identifier:
        users = users_with_email(identifier)
        if len({u.fin_kod for u in users}) != 1:
            return None, None
        user = users[0]
    else:
        user = User.query.filter_by(fin_kod=identifier).first()
    if not user:
        return None, None
    return user, Auth.query.filter_by(fin_kod=user.fin_kod).first()


def email_taken(email, exclude_fin=None):
    """True when the address already signs somebody else in."""
    email = normalise_email(email)
    if not email:
        return False
    if any(u.fin_kod != exclude_fin for u in users_with_email(email)):
        return True
    account = Auth.query.filter(func.lower(Auth.fin_kod) == email).first()
    return account is not None and account.fin_kod != exclude_fin
