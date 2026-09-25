from functools import wraps
from flask import request, jsonify
from utils.jwt_util import decode_auth_token
from exceptions.exception import handle_forbidden
from exceptions.exception import handle_unauthorized
from exceptions.exception import handle_role_forbidden

def role_required(required_roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            auth_header = request.headers.get('Authorization')
            if not auth_header:
                return handle_unauthorized(403, 'Authorization token is missing.')

            try:
                token = auth_header.split(" ")[1]
                payload = decode_auth_token(token)

                if payload is None:
                    return handle_unauthorized(403, 'Token is invalid or expired.')


                try:
                    user_role_code = int(payload.get('role_code', -1))
                except ValueError:
                    return handle_unauthorized(403, 'Role code is not a valid integer.')


                if user_role_code not in required_roles:
                    return handle_role_forbidden(403, "User does not have the required role to access this endpoint.")

                g.user = payload

            except Exception as e:
                return handle_unauthorized(401, 'Invalid or malformed token.')

            return f(*args, **kwargs)
        return decorated_function
    return decorator