from functools import wraps

from flask import g, jsonify, redirect, request, session, url_for
from werkzeug.security import check_password_hash

import db
import i18n


def load_user():
    user_id = session.get("user_id")
    if not user_id:
        g.user = None
        return

    user = db.get_user_by_id(user_id)
    if not user or user.get("status", db.USER_ACTIVE) != db.USER_ACTIVE:
        session.clear()
        g.user = None
        return

    g.user = user


def _is_api_request():
    return request.path.startswith("/api/")


def _login_required_response():
    if _is_api_request():
        locale = i18n.resolve_locale(request.headers.get("Accept-Language"))
        return jsonify({"success": False, "error": i18n.translate(locale, "error.authentication_required")}), 401
    return redirect(url_for("login"))


def _forbidden_response():
    if _is_api_request():
        locale = i18n.resolve_locale(request.headers.get("Accept-Language"))
        return jsonify({"success": False, "error": i18n.translate(locale, "error.forbidden")}), 403
    return "Forbidden", 403


def login_required(view_func):
    @wraps(view_func)
    def decorated(*args, **kwargs):
        if not g.get("user"):
            return _login_required_response()
        return view_func(*args, **kwargs)

    return decorated


def admin_required(view_func):
    @wraps(view_func)
    def decorated(*args, **kwargs):
        if not g.get("user"):
            return _login_required_response()
        if g.user.get("role") != "admin":
            return _forbidden_response()
        return view_func(*args, **kwargs)

    return decorated


def self_or_admin_required(param_name: str = "user_id"):
    def decorator(view_func):
        @wraps(view_func)
        def decorated(*args, **kwargs):
            user = g.get("user")
            if not user:
                return _login_required_response()
            if user.get("role") == "admin":
                return view_func(*args, **kwargs)
            current_user_id = int(user.get("id") or 0)
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
    if user.get("auth_source", db.AUTH_SOURCE_LOCAL) != db.AUTH_SOURCE_LOCAL:
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
