from functools import wraps

from flask import g, jsonify, redirect, request, session, url_for
from werkzeug.security import check_password_hash

import db


def load_user():
    g.user = db.get_user_by_id(session.get("user_id"))


def _is_api_request():
    return request.path.startswith("/api/")


def _login_required_response():
    if _is_api_request():
        return jsonify({"success": False, "error": "Authentication required"}), 401
    return redirect(url_for("login"))


def _forbidden_response():
    if _is_api_request():
        return jsonify({"success": False, "error": "Forbidden"}), 403
    return "Forbidden", 403


def login_required(view_func):
    @wraps(view_func)
    def decorated(*args, **kwargs):
        if not session.get("user_id"):
            return _login_required_response()
        return view_func(*args, **kwargs)

    return decorated


def admin_required(view_func):
    @wraps(view_func)
    def decorated(*args, **kwargs):
        if not session.get("user_id"):
            return _login_required_response()
        if session.get("role") != "admin":
            return _forbidden_response()
        return view_func(*args, **kwargs)

    return decorated


def self_or_admin_required(param_name: str = "user_id"):
    def decorator(view_func):
        @wraps(view_func)
        def decorated(*args, **kwargs):
            if not session.get("user_id"):
                return _login_required_response()
            if session.get("role") == "admin":
                return view_func(*args, **kwargs)
            current_user_id = int(session.get("user_id") or 0)
            requested_user_id = int(kwargs.get(param_name) or 0)
            if current_user_id != requested_user_id:
                return _forbidden_response()
            return view_func(*args, **kwargs)

        return decorated

    return decorator


def verify_local_password(username: str, password: str):
    user = db.get_user_by_username(username)
    if not user:
        return None
    if check_password_hash(user["password_hash"], password):
        return user
    return None


def verify_local_admin_password(username: str, password: str):
    user = verify_local_password(username, password)
    if not user:
        return None
    if user.get("role") != "admin":
        return None
    if user.get("auth_source", db.AUTH_SOURCE_LOCAL) != db.AUTH_SOURCE_LOCAL:
        return None
    if user.get("status", db.USER_ACTIVE) != db.USER_ACTIVE:
        return None
    return user


def verify_password(username: str, password: str):
    return verify_local_password(username, password)


def change_password(user_id: int, new_password: str) -> None:
    db.update_user_password(user_id, new_password)
