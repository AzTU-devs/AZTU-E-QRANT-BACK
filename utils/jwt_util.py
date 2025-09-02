import jwt
import datetime
from flask import current_app
from models.userModel import User


from flask import current_app

def encode_auth_token(user_id, fin_kod, profile_completed, role):
    user = User.query.filter_by(fin_kod=fin_kod).first()
    if not user:
        raise ValueError("User not found")

    expiration_time = datetime.datetime.utcnow() + datetime.timedelta(hours=1)
    payload = {
        'sub': str(user_id),
        'fin_kod': str(fin_kod),
        'profile_completed': str(profile_completed),
        'role': role,
        'exp': expiration_time
    }
    secret_key = current_app.config.get('SECRET_KEY')
    if not secret_key or not isinstance(secret_key, str):
        raise ValueError("SECRET_KEY is missing or not a valid string")
    token = jwt.encode(payload, secret_key, algorithm='HS256')
    if isinstance(token, bytes):
        token = token.decode('utf-8')
    return token


def decode_auth_token(auth_token):
    try:
        current_app.logger.debug(f"Decoding token: {auth_token}")

        secret_key = current_app.config.get('SECRET_KEY')
        if not secret_key or not isinstance(secret_key, str):
            raise ValueError("SECRET_KEY is missing or not a valid string")
        payload = jwt.decode(auth_token, secret_key, algorithms=['HS256'], options={"require": ["exp"]})

        current_app.logger.debug(f"Decoded payload: {payload}")

        return {
            'user_id': payload['sub'],
            'fin_kod': payload['fin_kod'],
            'profile_completed': payload['profile_completed'],
            'role': payload['role']
        }

    except jwt.ExpiredSignatureError:
        current_app.logger.warning("Token has expired")
        return None
    except jwt.InvalidTokenError as e:
        current_app.logger.warning(f"Invalid token: {e}")
        return None
    except Exception as e:
        current_app.logger.error(f"Error decoding token: {e}")
        return None
    
def encode_otp_token(fin_kod):
    user = User.query.filter_by(fin_kod=fin_kod).first()
    if not user:
        raise ValueError("User not found")

    expiration_time = datetime.datetime.utcnow() + datetime.timedelta(hours=1)
    payload = {
        'fin_kod': str(fin_kod),
        'exp': expiration_time
    }
    secret_key = current_app.config.get('SECRET_KEY')
    if not secret_key or not isinstance(secret_key, str):
        raise ValueError("SECRET_KEY is missing or not a valid string")
    token = jwt.encode(payload, secret_key, algorithm='HS256')
    if isinstance(token, bytes):
        token = token.decode('utf-8')
    return token

def decode_otp_token(auth_token):
    try:
        current_app.logger.debug(f"Decoding token: {auth_token}")

        secret_key = current_app.config.get('SECRET_KEY')
        if not secret_key or not isinstance(secret_key, str):
            raise ValueError("SECRET_KEY is missing or not a valid string")
        payload = jwt.decode(auth_token, secret_key, algorithms=['HS256'], options={"require": ["exp"]})

        current_app.logger.debug(f"Decoded payload: {payload}")

        return {
            'fin_kod': payload['fin_kod'],
        }

    except jwt.ExpiredSignatureError:
        current_app.logger.warning("Token has expired")
        return None
    except jwt.InvalidTokenError as e:
        current_app.logger.warning(f"Invalid token: {e}")
        return None
    except Exception as e:
        current_app.logger.error(f"Error decoding token: {e}")
        return None