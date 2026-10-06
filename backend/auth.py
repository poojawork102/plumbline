"""Bearer-token auth with two roles: `user` and `admin` (the reviewing authority).

The frontend (Vercel) and API (Render) live on different origins, so we use
signed bearer tokens in the Authorization header rather than cookies -- no
third-party-cookie or SameSite issues, and no CSRF surface.

Tokens are signed with SECRET_KEY and carry only the user id; the role is
re-read from the database on every request, so demoting an admin takes
effect immediately.
"""
from functools import wraps

from flask import current_app, g, jsonify, request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

import db

TOKEN_MAX_AGE_S = 7 * 24 * 3600
_SALT = "plumbline-auth"


def _serializer():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt=_SALT)


def issue_token(user):
    return _serializer().dumps({"uid": user["id"]})


def user_from_token(token):
    try:
        data = _serializer().loads(token, max_age=TOKEN_MAX_AGE_S)
    except (BadSignature, SignatureExpired):
        return None
    return db.get_user(data.get("uid"))


def current_user():
    header = request.headers.get("Authorization", "")
    if not header.lower().startswith("bearer "):
        return None
    return user_from_token(header[7:].strip())


def require_auth(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = current_user()
        if user is None:
            return jsonify({"status": "error", "message": "Sign in required"}), 401
        g.user = user
        return fn(*args, **kwargs)
    return wrapper


def require_admin(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = current_user()
        if user is None:
            return jsonify({"status": "error", "message": "Sign in required"}), 401
        if user["role"] != "admin":
            return jsonify({"status": "error", "message": "Admin access required"}), 403
        g.user = user
        return fn(*args, **kwargs)
    return wrapper
