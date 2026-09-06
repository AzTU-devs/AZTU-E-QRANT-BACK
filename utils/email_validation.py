"""Checking that an e-mail address is worth sending to.

An expert learns about their appointment, and receives the one-time password
they log in with, entirely by e-mail. If the address is wrong nobody finds out
until the expert never appears — so the address is checked before the account
is created, and then confirmed by a link the expert has to click.

Three levels, cheapest first:
  1. syntax        — is it shaped like an address at all
  2. deliverability — does the domain actually publish a mail server (DNS MX)
  3. confirmation   — did a human at that address click the link we sent

Only the third proves the address belongs to the expert, which is why it is the
one that gates assignment.
"""

import re
import socket
import secrets
import logging

logger = logging.getLogger(__name__)

# Deliberately conservative: one @, a dotted domain, no spaces or angle
# brackets. The RFC grammar allows far stranger things than anyone here types.
EMAIL_PATTERN = re.compile(
    r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9]([A-Za-z0-9\-]*[A-Za-z0-9])?"
    r"(\.[A-Za-z0-9]([A-Za-z0-9\-]*[A-Za-z0-9])?)+$"
)

# Typos common enough to be worth catching before the mail bounces.
DOMAIN_TYPOS = {
    'gmial.com': 'gmail.com',
    'gmai.com': 'gmail.com',
    'gmail.co': 'gmail.com',
    'gnail.com': 'gmail.com',
    'hotmial.com': 'hotmail.com',
    'yahho.com': 'yahoo.com',
    'mail.ur': 'mail.ru',
}


def normalise_email(value):
    """Trim and lower-case; addresses are compared and stored in this form."""
    return (value or '').strip().lower()


def has_valid_syntax(email):
    return bool(EMAIL_PATTERN.match(email or '')) and len(email) <= 254


def suggest_domain_fix(email):
    """A likely correction for a mistyped domain, or None."""
    domain = (email or '').rsplit('@', 1)[-1]
    fixed = DOMAIN_TYPOS.get(domain)
    return email.replace('@' + domain, '@' + fixed) if fixed else None


def domain_accepts_mail(email, timeout=5):
    """True when the domain publishes a mail exchanger.

    Uses dnspython when it is installed and falls back to resolving the host,
    which catches the common case of a domain that does not exist at all.
    Returns True when the check cannot be performed, so a resolver problem on
    our side never blocks a legitimate address.
    """
    domain = (email or '').rsplit('@', 1)[-1]
    if not domain:
        return False

    try:
        import dns.resolver  # optional dependency
    except ImportError:
        try:
            socket.setdefaulttimeout(timeout)
            socket.gethostbyname(domain)
            return True
        except socket.gaierror:
            return False
        except Exception:
            logger.warning("Could not check MX for %s; allowing it through", domain)
            return True

    try:
        resolver = dns.resolver.Resolver()
        resolver.lifetime = timeout
        resolver.timeout = timeout
        answers = resolver.resolve(domain, 'MX')
        return len(answers) > 0
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
        return False
    except Exception:
        logger.warning("Could not check MX for %s; allowing it through", domain)
        return True


def validate_expert_email(email, check_dns=True):
    """(normalised_email, error_message). `error_message` is None when usable."""
    normalised = normalise_email(email)

    if not normalised:
        return normalised, 'E-poçt ünvanı tələb olunur.'

    if not has_valid_syntax(normalised):
        return normalised, 'E-poçt ünvanı düzgün formatda deyil.'

    suggestion = suggest_domain_fix(normalised)
    if suggestion:
        return normalised, f'E-poçt ünvanında yazı xətası ola bilər. Bunu nəzərdə tuturdunuz? {suggestion}'

    if check_dns and not domain_accepts_mail(normalised):
        domain = normalised.rsplit('@', 1)[-1]
        return normalised, f'"{domain}" domeni e-poçt qəbul etmir. Ünvanı yoxlayın.'

    return normalised, None


def new_verification_token():
    return secrets.token_urlsafe(32)[:64]


def new_one_time_password(length=10):
    """A readable one-time password.

    The alphabet omits characters that are easy to confuse when retyping from
    an e-mail: O/0, I/l/1.
    """
    alphabet = 'ABCDEFGHJKMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789'
    return ''.join(secrets.choice(alphabet) for _ in range(length))
