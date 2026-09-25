import jwt
import hashlib
import datetime
from flask import current_app
from models.userModel import User
from models.expertModel import EXPERT_ROLE

# Every token says what it is for. An access token must never be accepted as a
# password-reset token or vice versa — both used to carry the same `fin_kod` +
# `exp` shape, so any sign-in token doubled as a reset token.
ACCESS_TOKEN = 'access'
RESET_TOKEN = 'pwd_reset'

RESET_TOKEN_MINUTES = 15


def _secret():
    secret_key = current_app.config.get('SECRET_KEY')
    if not secret_key or not isinstance(secret_key, str):
        raise ValueError("SECRET_KEY is missing or not a valid string")
    return secret_key


def _encode(payload):
    token = jwt.encode(payload, _secret(), algorithm='HS256')
    if isinstance(token, bytes):
        token = token.decode('utf-8')
    return token


def password_fingerprint(password_hash):
    """Short digest of the CURRENT password hash, embedded in a reset token.

    Once the password changes the digest no longer matches, so a reset link
    works exactly once and dies with the password it was issued against.
    """
    return hashlib.sha256((password_hash or '').encode('utf-8')).hexdigest()[:32]


def encode_auth_token(user_id, fin_kod, profile_completed, role):
    user = User.query.filter_by(fin_kod=fin_kod).first()
    if not user:
        raise ValueError("User not found")

    expiration_time = datetime.datetime.utcnow() + datetime.timedelta(hours=1)
    return _encode({
        'sub': str(user_id),
        'fin_kod': str(fin_kod),
        'profile_completed': str(profile_completed),
        'role': role,
        'typ': ACCESS_TOKEN,
        'exp': expiration_time
    })


def encode_expert_token(user_id, email):
    """A token for an expert.

    `encode_auth_token` looks up a `User` profile row, which experts do not
    have — they live in `experts` + `auth` only — so they get their own issuer
    with the same payload shape.
    """
    expiration_time = datetime.datetime.utcnow() + datetime.timedelta(hours=8)
    return _encode({
        'sub': str(user_id),
        'fin_kod': str(email),
        'profile_completed': '1',
        'role': EXPERT_ROLE,
        'typ': ACCESS_TOKEN,
        'exp': expiration_time
    })


def decode_auth_token(auth_token):
    """Payload of a valid ACCESS token, or None. Tokens are never logged."""
    try:
        payload = jwt.decode(auth_token, _secret(), algorithms=['HS256'], options={"require": ["exp", "sub"]})
        # Tokens issued before this field existed carry no `typ`; they expire
        # on their own within hours. A reset token is never an access token.
        if payload.get('typ', ACCESS_TOKEN) != ACCESS_TOKEN:
            return None
        return {
            'user_id': payload['sub'],
            'fin_kod': payload['fin_kod'],
            'profile_completed': payload.get('profile_completed'),
            'role': payload.get('role')
        }
    except jwt.ExpiredSignatureError:
        current_app.logger.info("Rejected an expired access token")
        return None
    except jwt.InvalidTokenError:
        current_app.logger.warning("Rejected an invalid access token")
        return None
    except Exception:
        current_app.logger.exception("Error decoding access token")
        return None


def encode_otp_token(fin_kod, password_hash):
    """Short-lived, single-use password-reset token issued after a valid OTP."""
    user = User.query.filter_by(fin_kod=fin_kod).first()
    if not user:
        raise ValueError("User not found")

    expiration_time = datetime.datetime.utcnow() + datetime.timedelta(minutes=RESET_TOKEN_MINUTES)
    return _encode({
        'fin_kod': str(fin_kod),
        'typ': RESET_TOKEN,
        'pwh': password_fingerprint(password_hash),
        'exp': expiration_time
    })


def decode_otp_token(auth_token):
    """{'fin_kod', 'pwh'} of a valid RESET token, or None."""
    try:
        payload = jwt.decode(auth_token, _secret(), algorithms=['HS256'], options={"require": ["exp"]})
        if payload.get('typ') != RESET_TOKEN or 'pwh' not in payload:
            return None
        return {'fin_kod': payload['fin_kod'], 'pwh': payload['pwh']}
    except jwt.ExpiredSignatureError:
        current_app.logger.info("Rejected an expired reset token")
        return None
    except jwt.InvalidTokenError:
        current_app.logger.warning("Rejected an invalid reset token")
        return None
    except Exception:
        current_app.logger.exception("Error decoding reset token")
        return None
