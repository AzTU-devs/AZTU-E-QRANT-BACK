from flask import Flask, jsonify

app = Flask(__name__)

# global for 500 error

@app.errorhandler(Exception)
def handle_global_exception(e):
    response = {
        "error": "Internal Server Error",
        "message": str(e)
    }
    return jsonify(response), 500

# 4xx

# handle not_found error

@app.errorhandler(404)
def handle_not_found(e):
    return jsonify({"status" : 404, "message": "User not found", "error_code":  "NOT_FOUND"}), 404

@app.errorhandler(404)
def handle_specific_not_found(message, legacy_message=None):
    # Declared long ago as (e, message), but every call site passes only the
    # message — which raised a TypeError and surfaced as a 500 with a Python
    # error string. The second parameter keeps the old two-argument shape working.
    if legacy_message is not None:
        message = legacy_message
    return jsonify({"status": 404, "message" : message, "error_code" : "NOT_FOUND"}), 404

# handle missing_field error

@app.errorhandler(404)
def handle_missing_field(e):
    return({"status": 400, "message": "Missing field", "error_code": "MISSING_FIELD"}), 400

# handle conflict

@app.errorhandler(409)
def handle_conflict(e):
    return jsonify({"status": 409, "message": "User exists", "error_code" : "CONFLICT"}), 409

# handle token missing (forbidden) 403

@app.errorhandler(403)
def handle_forbidden(e):
    return jsonify({"status": 403, "message" : "Token is missing.", "error_code" : "FORBIDDEN"}), 403

# handle token role

@app.errorhandler(403)
def handle_role_forbidden(e, message):
    return jsonify({"status": 403, "message": message, "error_code": "FORBIDDEN"})

# handle unauthorized

def handle_unauthorized(status_code=401, message="Unauthorized"):
    response = jsonify({
        "error": "Unauthorized",
        "message": message
    })
    response.status_code = status_code
    return response

# OK - 2xx

# handle sign-in success

def handle_signin_success(data, message, token):
    return jsonify({
        "status": 200,
        "message": message,
        "data": data,
        "token": token,
        "success_code": "SUCCESS"
    }), 200

# handle success

def handle_success(data, message):
    return jsonify({
        "status": 200,
        "message": message,
        "data" : data,
        "success_code" : "SUCCESS"
    })

#handle creation

def handle_creation(message):
    return jsonify({
        "status": 201,
        "message": message,
        "success_code": "CREATED"
    }), 201