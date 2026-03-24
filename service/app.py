from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
import inspect
import os
from pathlib import Path
import sys
from urllib.parse import urlparse

from flask import Flask, abort, g, jsonify, redirect, render_template, request, session, url_for

import auth as auth_module
import db
import exception_logger


BASE_DIR = Path(__file__).resolve().parent
DOCS_DIR = BASE_DIR.parent / "docs"
API_DOC_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")
FILTER_FIELDS = ("agent_type", "agent_version", "model_name")
VALID_WINDOWS = {"day", "week", "all"}
VALID_TIMELINE_WINDOWS = {"week", "month"}


app = Flask(__name__)
app.secret_key = os.getenv("MY_FLASK_SECRET_KEY", "change-me-in-env")
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=False,
)


def _split_header_values(raw_value: str):
    return [item.strip() for item in (raw_value or "").split(",") if item.strip()]


def _normalize_origin(raw_value: str) -> str:
    parsed = urlparse(raw_value or "")
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"


def _allowed_origins():
    origins = {_normalize_origin(request.host_url)}
    if request.host:
        origins.add(f"http://{request.host.lower()}")
        origins.add(f"https://{request.host.lower()}")
    for item in _split_header_values(request.headers.get("X-Forwarded-Host", "")):
        origins.add(f"http://{item.lower()}")
        origins.add(f"https://{item.lower()}")
    return {origin for origin in origins if origin}


def _is_origin_valid_for_state_change() -> bool:
    origin = (request.headers.get("Origin") or "").strip()
    referer = (request.headers.get("Referer") or "").strip()
    if origin:
        return _normalize_origin(origin) in _allowed_origins()
    if referer:
        return _normalize_origin(referer) in _allowed_origins()
    return True


def _requested_window(valid_windows: set[str] | None = None, default: str = "all") -> str:
    allowed = valid_windows or VALID_WINDOWS
    window = (request.args.get("window") or default).strip().lower()
    return window if window in allowed else default


def _requested_filters() -> dict[str, str]:
    return {
        field: (request.args.get(field) or "").strip()
        for field in FILTER_FIELDS
        if (request.args.get(field) or "").strip()
    }


def _hook_key() -> str:
    return (
        request.headers.get("X-Hook-Key")
        or request.headers.get("X-TokenLeague-Hook-Key")
        or ""
    ).strip()


def _hook_user():
    return db.get_user_by_hook_key(_hook_key())


def _missing_fields(payload: dict, required_fields: tuple[str, ...]) -> list[str]:
    missing = []
    for field in required_fields:
        value = payload.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            missing.append(field)
    return missing


def _json_error(message: str, status_code: int):
    return jsonify({"success": False, "error": message}), status_code


def _log_ingest(
    endpoint: str,
    outcome: str,
    *,
    user=None,
    payload: dict | None = None,
    reason: str | None = None,
    missing_fields: list[str] | None = None,
):
    parts = [f"ingest/{endpoint} {outcome}"]
    if reason:
        parts.append(f"reason={reason}")
    if missing_fields:
        parts.append(f"missing_fields={','.join(missing_fields)}")
    if user:
        parts.append(f"username={user['username']}")
        parts.append(f"user_id={user['id']}")
    if payload:
        external_event_id = (payload.get("external_event_id") or "").strip()
        external_task_id = (payload.get("external_task_id") or "").strip()
        project_name = (payload.get("project_name") or "").strip()
        agent_type = (payload.get("agent_type") or "").strip()
        agent_version = (payload.get("agent_version") or "").strip()
        model_name = (payload.get("model_name") or "").strip()
        if external_event_id:
            parts.append(f"external_event_id={external_event_id}")
        if external_task_id:
            parts.append(f"external_task_id={external_task_id}")
        if project_name:
            parts.append(f"project_name={project_name}")
        if agent_type:
            parts.append(f"agent_type={agent_type}")
        if agent_version:
            parts.append(f"agent_version={agent_version}")
        if model_name:
            parts.append(f"model_name={model_name}")
    parts.append(f"remote_addr={request.remote_addr or '-'}")
    print(" ".join(parts), file=sys.stderr, flush=True)


@app.before_request
def before_request():
    auth_module.load_user()

    if request.method in {"POST", "PUT", "PATCH", "DELETE"} and session.get("user_id"):
        if not _is_origin_valid_for_state_change():
            if request.path.startswith("/api/"):
                return jsonify({"success": False, "error": "Origin validation failed"}), 403
            return "Origin validation failed", 403


@app.after_request
def add_security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault(
        "Permissions-Policy",
        "geolocation=(), microphone=(), camera=()",
    )
    return response


@app.context_processor
def inject_shell_context():
    return {
        "project_title": db.get_setting("project_title") or db.DEFAULT_PROJECT_TITLE,
        "project_subtitle": db.get_setting("project_subtitle") or db.DEFAULT_PROJECT_SUBTITLE,
        "format_token_count": format_token_count,
    }


exception_logger.init_app(app)


def _extract_api_methods(rule):
    return [method for method in API_DOC_METHODS if method in rule.methods]


def _format_api_resource_name(route_path: str) -> str:
    resource_path = route_path.removeprefix("/api").strip("/")
    if not resource_path:
        return "API"
    parts = []
    for segment in resource_path.split("/"):
        if segment.startswith("<") and segment.endswith(">"):
            continue
        parts.append(segment.replace("-", " ").replace("_", " "))
    return " / ".join(parts) if parts else "Dynamic resource"


def _trim_trailing_decimal(value: float) -> str:
    rounded = Decimal(str(value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    text = format(rounded, "f")
    return text[:-2] if text.endswith(".0") else text


def format_token_count(value: int | float | None) -> str:
    if value is None:
        return "0"

    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)

    sign = "-" if number < 0 else ""
    abs_value = abs(number)
    for divisor, suffix in (
        (1_000_000_000, "B"),
        (1_000_000, "M"),
        (1_000, "K"),
    ):
        if abs_value >= divisor:
            return f"{sign}{_trim_trailing_decimal(abs_value / divisor)}{suffix}"

    if abs_value.is_integer():
        return f"{sign}{int(abs_value)}"
    return f"{sign}{_trim_trailing_decimal(abs_value)}"


def _infer_api_description(rule, methods, view_func):
    if view_func:
        doc = inspect.getdoc(view_func)
        if doc:
            return doc.splitlines()[0].strip()
    action_map = {
        "GET": "Get",
        "POST": "Create",
        "PUT": "Update",
        "PATCH": "Update",
        "DELETE": "Delete",
    }
    resource = _format_api_resource_name(rule.rule)
    if len(methods) == 1:
        return f"{action_map.get(methods[0], 'Operate')} {resource}"
    return f"Operate {resource}"


def _build_api_list():
    api_items = []
    for rule in app.url_map.iter_rules():
        if not rule.rule.startswith("/api"):
            continue
        methods = _extract_api_methods(rule)
        if not methods:
            continue
        view_func = app.view_functions.get(rule.endpoint)
        api_items.append(
            {
                "name": _format_api_resource_name(rule.rule),
                "description": _infer_api_description(rule, methods, view_func),
                "endpoint": rule.rule,
                "methods": methods,
            }
        )
    api_items.sort(key=lambda item: (item["endpoint"], item["methods"][0]))
    return api_items


def _get_doc_list():
    if not DOCS_DIR.exists():
        return []
    docs = []
    for path in sorted(DOCS_DIR.glob("*.md")):
        title = path.stem.replace("-", " ").replace("_", " ").title()
        with path.open("r", encoding="utf-8") as handle:
            first_line = handle.readline().strip()
        if first_line.startswith("# "):
            title = first_line[2:].strip()
        docs.append({"path": path.name, "title": title})
    return docs


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/")
def index():
    if session.get("user_id"):
        return redirect(url_for("leaderboard"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_id"):
        return redirect(url_for("leaderboard"))

    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = auth_module.verify_password(username, password)
        if user and user.get("status", db.USER_ACTIVE) == db.USER_ACTIVE:
            session.clear()
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["role"] = user["role"]
            return redirect(url_for("leaderboard"))
        error = "Invalid username or password"

    return render_template("login.html", error=error)


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/leaderboard")
@auth_module.login_required
def leaderboard():
    window = _requested_window()
    filters = _requested_filters()
    rows = db.get_leaderboard(window=window, filters=filters)
    return render_template(
        "leaderboard.html",
        window=window,
        filters=filters,
        rows=rows,
    )


@app.route("/users/<int:user_id>")
@auth_module.login_required
def user_detail(user_id: int):
    window = _requested_window()
    filters = _requested_filters()
    stats = db.get_user_stats(user_id, window=window, filters=filters)
    if not stats:
        abort(404)
    return render_template(
        "user_detail.html",
        stats=stats,
        window=window,
        filters=filters,
    )


@app.route("/settings", methods=["GET", "POST"])
@auth_module.login_required
def settings():
    message = None
    if request.method == "POST":
        project_title = (request.form.get("project_title") or "").strip()
        project_subtitle = (request.form.get("project_subtitle") or "").strip()
        if project_title:
            db.set_setting("project_title", project_title)
            db.set_setting("project_subtitle", project_subtitle)
            message = "Project settings updated"
    return render_template(
        "settings.html",
        users=db.get_all_users(),
        project_title=db.get_setting("project_title") or db.DEFAULT_PROJECT_TITLE,
        project_subtitle=db.get_setting("project_subtitle") or db.DEFAULT_PROJECT_SUBTITLE,
        message=message,
    )


@app.route("/admin/users", methods=["GET", "POST"])
@auth_module.admin_required
def admin_users():
    message = None
    error = None
    if request.method == "POST":
        action = (request.form.get("action") or "create_user").strip()
        try:
            if action == "rotate_hook_key":
                user_id = int(request.form.get("user_id") or "0")
                db.rotate_user_hook_key(user_id)
                message = "Hook key rotated"
            elif action == "toggle_status":
                user_id = int(request.form.get("user_id") or "0")
                next_status = (request.form.get("status") or db.USER_ACTIVE).strip()
                db.set_user_status(user_id, next_status)
                message = "User status updated"
            else:
                username = (request.form.get("username") or "").strip()
                display_name = (request.form.get("display_name") or "").strip()
                password = request.form.get("password") or ""
                if not username or not password:
                    error = "Username and password are required"
                else:
                    db.create_user(username, password, display_name=display_name or username)
                    message = f"User {username} created"
        except ValueError as exc:
            error = str(exc)

    return render_template(
        "admin_users.html",
        users=db.get_all_users(),
        message=message,
        error=error,
    )


@app.route("/admin/agents")
@auth_module.admin_required
def admin_agents():
    return render_template("admin_agents.html", agents=db.list_agent_catalog())


@app.route("/api/change-password", methods=["POST"])
@auth_module.login_required
def api_change_password():
    """Change current user password"""
    data = request.get_json(silent=True) or {}
    new_password = (data.get("new_password") or "").strip()
    if not new_password:
        return jsonify({"success": False, "error": "new_password is required"}), 400
    auth_module.change_password(session["user_id"], new_password)
    return jsonify({"success": True})


@app.route("/api/ingest/prompt-event", methods=["POST"])
def api_ingest_prompt_event():
    """Create prompt event usage record"""
    user = _hook_user()
    if not user:
        _log_ingest("prompt-event", "rejected", reason="invalid_hook_key")
        return _json_error("Valid hook key is required", 401)

    data = request.get_json(silent=True) or {}
    missing_fields = _missing_fields(
        data,
        (
            "external_event_id",
            "task_id",
            "project_name",
            "prompt_started_at",
            "prompt_finished_at",
            "input_token_count",
            "output_token_count",
            "agent_type",
            "agent_version",
            "model_name",
        ),
    )
    if missing_fields:
        _log_ingest(
            "prompt-event",
            "rejected",
            user=user,
            payload=data,
            reason="missing_fields",
            missing_fields=missing_fields,
        )
        return _json_error(f"Missing required fields: {', '.join(missing_fields)}", 400)

    event = db.upsert_prompt_event(user["id"], data)
    _log_ingest("prompt-event", "accepted", user=user, payload=event)
    return jsonify({"success": True, "event": {"external_event_id": event["external_event_id"]}})


@app.route("/api/ingest/task-run", methods=["POST"])
def api_ingest_task_run():
    """Create task run usage record"""
    user = _hook_user()
    if not user:
        _log_ingest("task-run", "rejected", reason="invalid_hook_key")
        return _json_error("Valid hook key is required", 401)

    data = request.get_json(silent=True) or {}
    missing_fields = _missing_fields(
        data,
        (
            "external_task_id",
            "project_name",
            "started_at",
            "finished_at",
            "prompt_count",
            "input_token_count",
            "output_token_count",
            "agent_type",
            "agent_version",
            "model_name",
        ),
    )
    if missing_fields:
        _log_ingest(
            "task-run",
            "rejected",
            user=user,
            payload=data,
            reason="missing_fields",
            missing_fields=missing_fields,
        )
        return _json_error(f"Missing required fields: {', '.join(missing_fields)}", 400)

    task_run = db.upsert_task_run(user["id"], data)
    _log_ingest("task-run", "accepted", user=user, payload=task_run)
    return jsonify({"success": True, "task_run": {"external_task_id": task_run["external_task_id"]}})


@app.route("/api/leaderboard")
@auth_module.login_required
def api_leaderboard():
    """Get token leaderboard"""
    window = _requested_window()
    filters = _requested_filters()
    return jsonify(
        {
            "success": True,
            "window": window,
            "filters": filters,
            "rows": db.get_leaderboard(window=window, filters=filters),
        }
    )


@app.route("/api/users/<int:user_id>/stats")
@auth_module.login_required
def api_user_stats(user_id: int):
    """Get single user token statistics"""
    window = _requested_window()
    filters = _requested_filters()
    stats = db.get_user_stats(user_id, window=window, filters=filters)
    if not stats:
        return _json_error("User not found", 404)
    return jsonify(stats)


@app.route("/api/users/<int:user_id>/projects")
@auth_module.login_required
def api_user_projects(user_id: int):
    """Get user token statistics grouped by project"""
    window = _requested_window()
    user = db.get_user_by_id(user_id)
    if not user:
        return _json_error("User not found", 404)
    return jsonify({
        "success": True,
        "window": window,
        "projects": db.get_user_project_breakdown(user_id, window=window),
    })


@app.route("/api/users/<int:user_id>/models")
@auth_module.login_required
def api_user_models(user_id: int):
    """Get user token statistics grouped by model"""
    window = _requested_window()
    user = db.get_user_by_id(user_id)
    if not user:
        return _json_error("User not found", 404)
    return jsonify({
        "success": True,
        "window": window,
        "models": db.get_user_model_breakdown(user_id, window=window),
    })


@app.route("/api/users/<int:user_id>/timeline")
@auth_module.login_required
def api_user_timeline(user_id: int):
    """Get user token usage timeline"""
    window = _requested_window(VALID_TIMELINE_WINDOWS, default="week")
    granularity = (request.args.get("granularity") or "hour").strip().lower()
    if granularity not in ("hour", "day", "week"):
        granularity = "hour"
    user = db.get_user_by_id(user_id)
    if not user:
        return _json_error("User not found", 404)
    return jsonify({
        "success": True,
        "window": window,
        "granularity": granularity,
        "timeline": db.get_user_time_series(user_id, window=window, granularity=granularity),
    })


@app.route("/api")
@auth_module.login_required
def api_list():
    """TokenLeague API list page"""
    return render_template("api_list.html", apis=_build_api_list())


@app.route("/docs")
@app.route("/docs/<path:filepath>")
@auth_module.login_required
def docs_page(filepath: str = "README.md"):
    if ".." in filepath or filepath.startswith("/"):
        return "Invalid path", 403
    target = DOCS_DIR / filepath
    if not target.exists():
        raw_markdown = f"# Not Found\n\nMissing document: {filepath}"
    else:
        raw_markdown = target.read_text(encoding="utf-8")
    return render_template(
        "docs.html",
        doc_list=_get_doc_list(),
        current_doc=filepath,
        raw_markdown=raw_markdown,
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5006")), debug=True)
