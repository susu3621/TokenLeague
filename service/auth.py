from functools import wraps

from flask import g, jsonify, redirect, request, session, url_for
from werkzeug.security import check_password_hash

import db


def load_user():
    g.user = db.get_user_by_id(session.get("user_id"))


def login_required(view_func):
    @wraps(view_func)
    def decorated(*args, **kwargs):
        if not session.get("user_id"):
            if request.path.startswith("/api/"):
                return jsonify({"success": False, "error": "Authentication required"}), 401
            return redirect(url_for("login"))
        return view_func(*args, **kwargs)

    return decorated


def admin_required(view_func):
    @wraps(view_func)
    def decorated(*args, **kwargs):
        if not session.get("user_id"):
            if request.path.startswith("/api/"):
                return jsonify({"success": False, "error": "Authentication required"}), 401
            return redirect(url_for("login"))
        if session.get("role") != "admin":
            if request.path.startswith("/api/"):
                return jsonify({"success": False, "error": "Admin role required"}), 403
            return redirect(url_for("settings"))
        return view_func(*args, **kwargs)

    return decorated


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
