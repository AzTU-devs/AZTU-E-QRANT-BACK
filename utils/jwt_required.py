from functools import wraps
from flask import request, g
from utils.jwt_util import decode_auth_token
from exceptions.exception import handle_unauthorized

# Endpoints an account that still carries a one-time password may reach. Until
# it is replaced, everything else is refused on the SERVER (the UI already
# redirects, but the API must not rely on that).
PASSWORD_CHANGE_ENDPOINTS = {'auth.change_password'}


def _bearer_token():
    header = request.headers.get('Authorization', '')
    scheme, _, token = header.partition(' ')
    if scheme.lower() != 'bearer' or not token.strip():
        return None
    return token.strip()


def authenticate_request():
    """Resolve the caller from the bearer token AND the live account row.

    Returns (user, error_response). The token alone is not trusted for the role:
    the account is re-read so that a blocked, deleted or re-roled user loses
    their old privileges immediately instead of when the token expires.
    """
    # Imported here: models import the db extension, which is set up after
    # this module is first imported by the controllers.
    from models.authModel import Auth

    token = _bearer_token()
    if not token:
        return None, handle_unauthorized(401, 'Authorization token is missing.')

    payload = decode_auth_token(token)
    if payload is None:
        return None, handle_unauthorized(401, 'Token is invalid or expired.')

    try:
        account_id = int(payload.get('user_id'))
    except (TypeError, ValueError):
        return None, handle_unauthorized(401, 'Token is invalid or expired.')

    account = Auth.query.get(account_id)
    if (
        account is None
        or account.fin_kod != payload.get('fin_kod')
        or not account.approved
        or account.blocked
        # A token minted before the account's last password change / reset /
        # block / logout carries a stale version and is rejected (B-L3).
        or int(payload.get('token_version', 0)) != int(account.token_version or 0)
    ):
        return None, handle_unauthorized(401, 'Token is invalid or expired.')

    user = dict(payload)
    user['role'] = account.project_role
    user['must_change_password'] = bool(account.must_change_password)
    return user, None


def token_required(allowed_roles=None):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            user, error = authenticate_request()
            if error:
                return error

            if user.get('must_change_password') and request.endpoint not in PASSWORD_CHANGE_ENDPOINTS:
                return handle_unauthorized(403, 'Password change required before continuing.')

            if allowed_roles is not None and user.get('role') not in allowed_roles:
                return handle_unauthorized(403, 'Access denied: role not allowed.')

            g.user = user
            return f(*args, **kwargs)

        # Read by the app-wide default-deny check in app.py: a view that is not
        # marked here and is not on the public allow-list is refused outright.
        decorated_function._requires_auth = True
        return decorated_function
    return decorator
