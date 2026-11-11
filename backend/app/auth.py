"""Token authentication and server-enforced role checks (the UI only hides buttons; the API decides)."""
import functools
from flask import g, request, current_app
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from werkzeug.security import check_password_hash
from . import config
from .util import ApiError

def _ser():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="campusops-auth")

def issue_token(user_id):
    return _ser().dumps({"uid": user_id})

def authenticate(c, username, password):
    row = c.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    if not row or not check_password_hash(row["password_hash"], password):
        raise ApiError(401, "bad_credentials", "Unknown user or wrong password")
    return row

def login_required(fn):
    @functools.wraps(fn)
    def wrapper(*a, **kw):
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            raise ApiError(401, "auth_required", "Missing bearer token")
        try:
            uid = _ser().loads(header[7:], max_age=config.TOKEN_MAX_AGE_S)["uid"]
        except SignatureExpired:
            raise ApiError(401, "token_expired", "Token expired; log in again")
        except BadSignature:
            raise ApiError(401, "token_invalid", "Invalid token")
        user = g.db.execute("SELECT id,username,display_name,role FROM users WHERE id=?", (uid,)).fetchone()
        if not user:
            raise ApiError(401, "token_invalid", "User no longer exists")
        g.user = dict(user)
        return fn(*a, **kw)
    return wrapper

def roles_required(*roles):
    def deco(fn):
        @functools.wraps(fn)
        @login_required
        def wrapper(*a, **kw):
            if g.user["role"] not in roles:
                raise ApiError(403, "forbidden", f"Role '{g.user['role']}' may not perform this action", required=list(roles))
            return fn(*a, **kw)
        return wrapper
    return deco
