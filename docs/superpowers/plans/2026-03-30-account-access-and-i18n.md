# Account Access and I18n Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restrict normal users to safe routes, add a self-service account page for API key and password management, and switch UI and Docs between Chinese and English from browser language with English fallback.

**Architecture:** Keep the current Flask + Jinja server-rendered structure. Add explicit authorization helpers in `service/auth.py`, a dedicated `/account` page with self-scoped APIs, and a small `service/i18n.py` helper for locale resolution and message lookup. Extend the existing docs route to resolve localized Markdown files without changing public URLs.

**Tech Stack:** Flask, Jinja, Python, pytest, in-memory test store, Marked.js

---

## File Map

**Create:**

- `service/i18n.py` - browser-language resolution and translation lookup helpers
- `service/templates/account.html` - self-service account page with API key and password UI
- `service/tests/test_i18n.py` - focused locale resolution and translated-shell coverage
- `docs/README.zh-CN.md` - Chinese variant of the root documentation page

**Modify:**

- `service/auth.py` - explicit forbidden responses and self-or-admin authorization
- `service/app.py` - locale injection, account route/API, user-detail authorization, docs localization
- `service/templates/base.html` - role-aware navigation, username menu, dynamic `lang`
- `service/templates/leaderboard.html` - self-link guard and translated shell strings
- `service/templates/docs.html` - translated docs UI shell
- `service/templates/login.html` - translated login copy
- `service/templates/local_admin_login.html` - translated recovery-login copy
- `service/templates/user_detail.html` - translated headings, selectors, empty states, and JS strings
- `service/templates/settings.html` - translated admin settings copy
- `service/templates/api_list.html` - translated API list copy
- `service/templates/admin_users.html` - translated admin user management copy
- `service/templates/admin_ldap.html` - translated LDAP admin copy
- `service/templates/admin_agents.html` - translated agent catalog copy
- `service/tests/conftest.py` - normal-user authenticated session fixture
- `service/tests/test_auth_flow.py` - normal-user access and account-page tests
- `service/tests/test_api_list_page.py` - admin API list and new account API endpoint assertions
- `service/tests/test_docs_page.py` - localized docs selection and fallback assertions
- `service/tests/test_token_league.py` - self-only user detail and leaderboard shell assertions

## Task 1: Lock Down Route Access for Normal Users

**Files:**

- Modify: `service/tests/conftest.py`
- Modify: `service/tests/test_auth_flow.py`
- Modify: `service/tests/test_api_list_page.py`
- Modify: `service/tests/test_token_league.py`
- Modify: `service/auth.py`
- Modify: `service/app.py`
- Modify: `service/templates/base.html`
- Modify: `service/templates/leaderboard.html`

- [ ] **Step 1: Add a normal-user session fixture and failing access tests**

Add this fixture to `service/tests/conftest.py`:

```python
@pytest.fixture
def user_session(client):
    from db import create_user

    user = create_user("alice", "secret123", display_name="Alice")
    with client.session_transaction() as session:
        session["user_id"] = user["id"]
        session["username"] = user["username"]
        session["role"] = user["role"]
    return client
```

Add these tests to `service/tests/test_auth_flow.py`:

```python
def test_settings_page_returns_403_for_normal_user(user_session):
    response = user_session.get("/settings")

    assert response.status_code == 403


def test_api_list_page_returns_403_for_normal_user(user_session):
    response = user_session.get("/api")

    assert response.status_code == 403
```

Add these tests to `service/tests/test_token_league.py`:

```python
def test_normal_user_can_only_open_their_own_user_detail(user_session):
    from db import create_user, get_user_by_username

    current_user = get_user_by_username("alice")
    other_user = create_user("bob", "secret123", display_name="Bob")

    own_response = user_session.get(f"/users/{current_user['id']}")
    forbidden_response = user_session.get(f"/users/{other_user['id']}")

    assert own_response.status_code == 200
    assert forbidden_response.status_code == 403


def test_normal_user_stats_api_rejects_other_user_ids(user_session):
    from db import create_user, get_user_by_username

    current_user = get_user_by_username("alice")
    other_user = create_user("bob", "secret123", display_name="Bob")

    own_response = user_session.get(f"/api/users/{current_user['id']}/stats")
    forbidden_response = user_session.get(f"/api/users/{other_user['id']}/stats")

    assert own_response.status_code == 200
    assert forbidden_response.status_code == 403


def test_normal_user_shell_hides_admin_and_system_links(user_session):
    response = user_session.get("/leaderboard")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Leaderboard" in html
    assert "Docs" in html
    assert "Settings" not in html
    assert "API" not in html
    assert "Admin Users" not in html
```

- [ ] **Step 2: Run the focused authorization tests to verify they fail**

Run:

```bash
pytest service/tests/test_auth_flow.py service/tests/test_token_league.py -k "403_for_normal_user or only_open_their_own_user_detail or rejects_other_user_ids or hides_admin_and_system_links" -q
```

Expected: FAIL because normal users can still access `/settings`, `/api`, and other users' detail routes, and the shared shell still shows admin/system links.

- [ ] **Step 3: Implement explicit forbidden responses and self-or-admin authorization**

Update `service/auth.py` to centralize unauthorized behavior:

```python
def _login_required_response():
    if request.path.startswith("/api/"):
        return jsonify({"success": False, "error": "Authentication required"}), 401
    return redirect(url_for("login"))


def _forbidden_response():
    if request.path.startswith("/api/"):
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
            if kwargs.get(param_name) == session.get("user_id"):
                return view_func(*args, **kwargs)
            return _forbidden_response()

        return decorated

    return decorator
```

Apply the new decorator in `service/app.py`:

```python
@app.route("/users/<int:user_id>")
@auth_module.self_or_admin_required()
def user_detail(user_id: int):
    window = _requested_user_detail_window()
    filters = _requested_filters()
    stats = db.get_user_stats(user_id, window=window, filters=filters)
    if not stats:
        abort(404)
    return render_template(
        "user_detail.html",
        stats=stats,
        window=window,
        window_label=_user_detail_window_label(window),
        filters=filters,
    )


@app.route("/settings", methods=["GET", "POST"])
@auth_module.admin_required
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


@app.route("/api/users/<int:user_id>/stats")
@auth_module.self_or_admin_required()
def api_user_stats(user_id: int):
    window = _requested_user_detail_window()
    filters = _requested_filters()
    stats = db.get_user_stats(user_id, window=window, filters=filters)
    if not stats:
        return _json_error("User not found", 404)
    return jsonify(stats)


@app.route("/api/users/<int:user_id>/projects")
@auth_module.self_or_admin_required()
def api_user_projects(user_id: int):
    window = _requested_user_detail_window()
    filters = _requested_filters()
    user = db.get_user_by_id(user_id)
    if not user:
        return _json_error("User not found", 404)
    return jsonify({
        "success": True,
        "window": window,
        "projects": db.get_user_project_breakdown(user_id, window=window, filters=filters),
    })


@app.route("/api/users/<int:user_id>/models")
@auth_module.self_or_admin_required()
def api_user_models(user_id: int):
    window = _requested_user_detail_window()
    filters = _requested_filters()
    user = db.get_user_by_id(user_id)
    if not user:
        return _json_error("User not found", 404)
    return jsonify({
        "success": True,
        "window": window,
        "models": db.get_user_model_breakdown(user_id, window=window, filters=filters),
    })


@app.route("/api/users/<int:user_id>/timeline")
@auth_module.self_or_admin_required()
def api_user_timeline(user_id: int):
    window = _requested_user_detail_window()
    filters = _requested_filters()
    granularity = "hour" if window == "today" else (request.args.get("granularity") or "hour").strip().lower()
    if granularity not in ("hour", "day", "week"):
        granularity = "hour"
    user = db.get_user_by_id(user_id)
    if not user:
        return _json_error("User not found", 404)
    return jsonify({
        "success": True,
        "window": window,
        "granularity": granularity,
        "timeline": db.get_user_time_series(user_id, window=window, granularity=granularity, filters=filters),
    })


@app.route("/api")
@auth_module.admin_required
def api_list():
    return render_template("api_list.html", apis=_build_api_list())
```

- [ ] **Step 4: Hide admin/system navigation and prevent misleading leaderboard links**

First, reduce normal-user navigation in `service/templates/base.html`:

```jinja
<div class="nav">
    <a href="{{ url_for('leaderboard') }}">Leaderboard</a>
    <a href="{{ url_for('docs_page') }}">Docs</a>
    {% if session.get('role') == 'admin' %}
    <a href="{{ url_for('settings') }}">Settings</a>
    <a href="{{ url_for('api_list') }}">API</a>
    <a href="{{ url_for('admin_users') }}">Admin Users</a>
    <a href="{{ url_for('admin_ldap') }}">LDAP</a>
    <a href="{{ url_for('admin_agents') }}">Agent Catalog</a>
    {% endif %}
    <form method="POST" action="{{ url_for('logout') }}" style="margin: 0;">
        <button type="submit">Log out</button>
    </form>
</div>
```

Then update `service/templates/leaderboard.html` so only self rows are linkable for normal users:

```jinja
<script>
    const viewerUserId = {{ g.user.id }};
    const viewerIsAdmin = {{ 'true' if session.get('role') == 'admin' else 'false' }};

    function renderUserCell(row) {
        const displayName = escapeHtml(row.display_name);
        const username = escapeHtml(row.username);
        if (viewerIsAdmin || Number(row.user_id) === viewerUserId) {
            return `<a href="/users/${encodeURIComponent(row.user_id)}">${displayName}</a><div class="muted">${username}</div>`;
        }
        return `${displayName}<div class="muted">${username}</div>`;
    }
```

Replace the current inline anchor creation with:

```javascript
<td>${renderUserCell(row)}</td>
```

- [ ] **Step 5: Run the focused authorization tests to verify they pass**

Run:

```bash
pytest service/tests/test_auth_flow.py service/tests/test_token_league.py -k "403_for_normal_user or only_open_their_own_user_detail or rejects_other_user_ids or hides_admin_and_system_links" -q
```

Expected: PASS

- [ ] **Step 6: Commit the access-control slice**

Run:

```bash
git add service/tests/conftest.py service/tests/test_auth_flow.py service/tests/test_token_league.py service/auth.py service/app.py service/templates/base.html service/templates/leaderboard.html
git commit -m "feat: restrict normal user access"
```

## Task 2: Add the Self-Service Account Page and API Key Rotation

**Files:**

- Modify: `service/tests/test_auth_flow.py`
- Modify: `service/tests/test_api_list_page.py`
- Modify: `service/tests/test_token_league.py`
- Modify: `service/templates/base.html`
- Create: `service/templates/account.html`
- Modify: `service/app.py`

- [ ] **Step 1: Add failing account page and API tests**

Add these tests to `service/tests/test_auth_flow.py`:

```python
def test_account_page_requires_login(client):
    response = client.get("/account")

    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_account_page_renders_current_user_hook_key(user_session):
    from db import get_user_by_username

    current_user = get_user_by_username("alice")
    response = user_session.get("/account")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert current_user["hook_key"] in html
    assert "/api/account/rotate-hook-key" in html
    assert "/api/change-password" in html


def test_rotate_hook_key_api_rotates_only_the_current_user_key(user_session):
    from db import create_user, get_user_by_username

    current_user = get_user_by_username("alice")
    other_user = create_user("bob", "secret123", display_name="Bob")

    response = user_session.post("/api/account/rotate-hook-key")

    assert response.status_code == 200
    payload = response.get_json()
    refreshed_current_user = get_user_by_username("alice")
    refreshed_other_user = get_user_by_username("bob")
    assert payload["success"] is True
    assert payload["hook_key"] == refreshed_current_user["hook_key"]
    assert refreshed_current_user["hook_key"] != current_user["hook_key"]
    assert refreshed_other_user["hook_key"] == other_user["hook_key"]
```

Add this test to `service/tests/test_api_list_page.py`:

```python
def test_build_api_list_contains_account_rotation_endpoint():
    from app import _build_api_list

    apis = _build_api_list()

    assert any(
        api["endpoint"] == "/api/account/rotate-hook-key" and api["methods"] == ["POST"]
        for api in apis
    )
```

Add this shell assertion to `service/tests/test_token_league.py`:

```python
def test_normal_user_shell_shows_account_menu_entry(user_session):
    response = user_session.get("/leaderboard")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "/account" in html
    assert "Alice" in html
```

- [ ] **Step 2: Run the focused account tests to verify they fail**

Run:

```bash
pytest service/tests/test_auth_flow.py service/tests/test_api_list_page.py service/tests/test_token_league.py -k "account_page or rotate_hook_key_api or account_rotation_endpoint or account_menu_entry" -q
```

Expected: FAIL because `/account` and `/api/account/rotate-hook-key` do not exist yet and the shell has no account entry.

- [ ] **Step 3: Add the account route and self-scoped rotation API**

Update `service/app.py`:

```python
@app.route("/account")
@auth_module.login_required
def account():
    account_user = db.get_user_by_id(session["user_id"])
    return render_template("account.html", account_user=account_user)


@app.route("/api/account/rotate-hook-key", methods=["POST"])
@auth_module.login_required
def api_account_rotate_hook_key():
    db.rotate_user_hook_key(session["user_id"])
    account_user = db.get_user_by_id(session["user_id"])
    return jsonify(
        {
            "success": True,
            "hook_key": account_user["hook_key"],
            "hook_key_created_at": account_user["hook_key_created_at"],
        }
    )
```

Create `service/templates/account.html`:

```jinja
{% extends "base.html" %}

{% block title %}Account | {{ project_title }}{% endblock %}

{% block content %}
<section class="stack">
    <div class="card">
        <h1 class="hero-title">Account</h1>
        <p class="muted">Manage your API key and password.</p>
    </div>

    <div class="card stack">
        <div>
            <label for="hook-key">API Key</label>
            <input id="hook-key" value="{{ account_user.hook_key }}" readonly data-account-hook-key>
            <p class="muted" data-account-hook-key-created-at>Generated: {{ account_user.hook_key_created_at or "-" }}</p>
        </div>
        <div style="display: flex; gap: 12px; flex-wrap: wrap;">
            <button type="button" class="btn-primary" data-account-copy>Copy API Key</button>
            <button type="button" data-account-rotate>Rotate API Key</button>
        </div>
        <p class="muted" data-account-hook-key-message></p>
    </div>

    <div class="card stack">
        <h2 style="margin-top: 0;">Change Password</h2>
        <form class="stack" data-account-password-form>
            <div>
                <label for="new_password">New Password</label>
                <input id="new_password" name="new_password" type="password" required>
            </div>
            <button class="btn-primary" type="submit">Save Password</button>
        </form>
        <p class="muted" data-account-password-message></p>
    </div>
</section>
{% endblock %}

{% block scripts %}
<script>
(function () {
    const hookKeyInput = document.querySelector("[data-account-hook-key]");
    const hookKeyMessage = document.querySelector("[data-account-hook-key-message]");
    const passwordForm = document.querySelector("[data-account-password-form]");
    const passwordMessage = document.querySelector("[data-account-password-message]");

    document.querySelector("[data-account-copy]").addEventListener("click", async function () {
        await navigator.clipboard.writeText(hookKeyInput.value);
        hookKeyMessage.textContent = "API key copied.";
    });

    document.querySelector("[data-account-rotate]").addEventListener("click", async function () {
        const response = await fetch("/api/account/rotate-hook-key", {method: "POST"});
        const payload = await response.json();
        hookKeyInput.value = payload.hook_key;
        hookKeyMessage.textContent = "API key rotated.";
    });

    passwordForm.addEventListener("submit", async function (event) {
        event.preventDefault();
        const formData = new FormData(passwordForm);
        const response = await fetch("/api/change-password", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({new_password: formData.get("new_password")}),
        });
        const payload = await response.json();
        passwordMessage.textContent = payload.success ? "Password updated." : payload.error;
    });
}());
</script>
{% endblock %}
```

- [ ] **Step 4: Add the username menu entry in the shared shell**

Update `service/templates/base.html` so the account page is reachable without adding a top-level system tab:

```jinja
<div class="nav">
    <a href="{{ url_for('leaderboard') }}">Leaderboard</a>
    <a href="{{ url_for('docs_page') }}">Docs</a>
    <details class="nav-menu">
        <summary>{{ g.user.display_name or g.user.username }}</summary>
        <div class="nav-menu-panel">
            <a href="{{ url_for('account') }}">Account</a>
        </div>
    </details>
    {% if session.get('role') == 'admin' %}
    <a href="{{ url_for('settings') }}">Settings</a>
    <a href="{{ url_for('api_list') }}">API</a>
    <a href="{{ url_for('admin_users') }}">Admin Users</a>
    <a href="{{ url_for('admin_ldap') }}">LDAP</a>
    <a href="{{ url_for('admin_agents') }}">Agent Catalog</a>
    {% endif %}
    <form method="POST" action="{{ url_for('logout') }}" style="margin: 0;">
        <button type="submit">Log out</button>
    </form>
</div>
```

Add matching styles near the existing `.nav` styles:

```css
.nav-menu {
    position: relative;
}

.nav-menu summary {
    list-style: none;
    color: var(--muted);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 8px 12px;
    cursor: pointer;
}

.nav-menu-panel {
    position: absolute;
    right: 0;
    top: calc(100% + 8px);
    min-width: 160px;
    padding: 8px;
    border: 1px solid var(--border);
    border-radius: 10px;
    background: var(--panel);
}
```

- [ ] **Step 5: Run the focused account tests to verify they pass**

Run:

```bash
pytest service/tests/test_auth_flow.py service/tests/test_api_list_page.py service/tests/test_token_league.py -k "account_page or rotate_hook_key_api or account_rotation_endpoint or account_menu_entry" -q
```

Expected: PASS

- [ ] **Step 6: Commit the account-management slice**

Run:

```bash
git add service/tests/test_auth_flow.py service/tests/test_api_list_page.py service/tests/test_token_league.py service/app.py service/templates/base.html service/templates/account.html
git commit -m "feat: add self-service account page"
```

## Task 3: Add Browser-Language UI Translation

**Files:**

- Create: `service/i18n.py`
- Create: `service/tests/test_i18n.py`
- Modify: `service/app.py`
- Modify: `service/templates/base.html`
- Modify: `service/templates/login.html`
- Modify: `service/templates/local_admin_login.html`
- Modify: `service/templates/leaderboard.html`
- Modify: `service/templates/docs.html`
- Modify: `service/templates/user_detail.html`
- Modify: `service/templates/settings.html`
- Modify: `service/templates/api_list.html`
- Modify: `service/templates/admin_users.html`
- Modify: `service/templates/admin_ldap.html`
- Modify: `service/templates/admin_agents.html`
- Modify: `service/templates/account.html`

- [ ] **Step 1: Add failing locale-resolution and translated-shell tests**

Create `service/tests/test_i18n.py`:

```python
def test_resolve_locale_prefers_chinese_variants():
    from i18n import resolve_locale

    assert resolve_locale("zh-CN,zh;q=0.9,en;q=0.8") == "zh-CN"
    assert resolve_locale("zh-TW,en;q=0.8") == "zh-CN"
    assert resolve_locale("en-US,en;q=0.9") == "en"


def test_login_page_renders_chinese_copy(client):
    response = client.get("/login", headers={"Accept-Language": "zh-CN,zh;q=0.9"})

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert '<html lang="zh-CN">' in html
    assert "登录" in html
    assert "用户名" in html
    assert "密码" in html


def test_leaderboard_page_renders_chinese_shell_copy(auth_session):
    response = auth_session.get("/leaderboard", headers={"Accept-Language": "zh-CN,zh;q=0.9"})

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Token 排行榜" in html
    assert "正在加载排行榜..." in html
    assert "排行榜尚在准备中" in html


def test_unknown_browser_language_falls_back_to_english(auth_session):
    response = auth_session.get("/leaderboard", headers={"Accept-Language": "fr-FR,fr;q=0.9"})

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert '<html lang="en">' in html
    assert "Loading leaderboard..." in html
```

- [ ] **Step 2: Run the focused i18n tests to verify they fail**

Run:

```bash
pytest service/tests/test_i18n.py -q
```

Expected: FAIL because locale resolution and translated template copy do not exist yet.

- [ ] **Step 3: Create the locale helper and inject it into request/template context**

Create `service/i18n.py`:

```python
SUPPORTED_LOCALES = ("en", "zh-CN")

MESSAGES = {
    "en": {
        "nav.leaderboard": "Leaderboard",
        "nav.docs": "Docs",
        "nav.account": "Account",
        "nav.settings": "Settings",
        "nav.api": "API",
        "nav.admin_users": "Admin Users",
        "nav.ldap": "LDAP",
        "nav.agent_catalog": "Agent Catalog",
        "nav.logout": "Log out",
        "login.title": "Login",
        "login.username": "Username",
        "login.password": "Password",
        "login.submit": "Sign in",
        "login.invalid_credentials": "Invalid username or password",
        "local_admin.title": "Local Admin Recovery",
        "local_admin.submit": "Sign in as local admin",
        "leaderboard.title": "Token Leaderboard",
        "leaderboard.loading": "Loading leaderboard...",
        "leaderboard.preparing": "Leaderboard is being prepared",
        "leaderboard.failed": "Failed to load leaderboard",
        "docs.title": "Docs",
        "docs.sidebar_title": "Documents",
        "account.title": "Account",
        "account.copy": "Copy API Key",
        "account.rotate": "Rotate API Key",
        "account.password_submit": "Save Password",
        "account.copied": "API key copied.",
        "account.rotated": "API key rotated.",
        "account.password_updated": "Password updated.",
        "user_detail.title": "User Detail",
        "user_detail.window.today": "Today",
        "user_detail.window.week": "Past 7 Days",
        "user_detail.window.month": "Past 30 Days",
        "user_detail.window.quarter": "Past 90 Days",
        "user_detail.loading": "Loading...",
        "user_detail.no_data": "No data in this window.",
        "settings.title": "League Settings",
        "api_list.title": "API List",
        "admin_users.title": "Admin Users",
        "admin_ldap.title": "LDAP Settings",
        "admin_agents.title": "Agent Catalog",
    },
    "zh-CN": {
        "nav.leaderboard": "排行榜",
        "nav.docs": "文档",
        "nav.account": "个人设置",
        "nav.settings": "系统设置",
        "nav.api": "接口",
        "nav.admin_users": "用户管理",
        "nav.ldap": "LDAP",
        "nav.agent_catalog": "Agent 目录",
        "nav.logout": "退出登录",
        "login.title": "登录",
        "login.username": "用户名",
        "login.password": "密码",
        "login.submit": "登录",
        "login.invalid_credentials": "用户名或密码错误",
        "local_admin.title": "本地管理员恢复登录",
        "local_admin.submit": "以本地管理员身份登录",
        "leaderboard.title": "Token 排行榜",
        "leaderboard.loading": "正在加载排行榜...",
        "leaderboard.preparing": "排行榜尚在准备中",
        "leaderboard.failed": "排行榜加载失败",
        "docs.title": "文档",
        "docs.sidebar_title": "文档列表",
        "account.title": "个人设置",
        "account.copy": "复制 API Key",
        "account.rotate": "重置 API Key",
        "account.password_submit": "保存密码",
        "account.copied": "API Key 已复制。",
        "account.rotated": "API Key 已重置。",
        "account.password_updated": "密码已更新。",
        "user_detail.title": "用户详情",
        "user_detail.window.today": "今天",
        "user_detail.window.week": "过去7天",
        "user_detail.window.month": "过去30天",
        "user_detail.window.quarter": "过去90天",
        "user_detail.loading": "加载中...",
        "user_detail.no_data": "当前时间范围内没有数据。",
        "settings.title": "系统设置",
        "api_list.title": "接口列表",
        "admin_users.title": "用户管理",
        "admin_ldap.title": "LDAP 设置",
        "admin_agents.title": "Agent 目录",
    },
}


def resolve_locale(header_value: str | None) -> str:
    for raw_part in (header_value or "").split(","):
        code = raw_part.split(";")[0].strip().lower()
        if code.startswith("zh"):
            return "zh-CN"
    return "en"


def translate(locale: str, key: str, **values) -> str:
    catalog = MESSAGES.get(locale, MESSAGES["en"])
    template = catalog.get(key, MESSAGES["en"].get(key, key))
    return template.format(**values)
```

Wire it into `service/app.py`:

```python
import i18n


@app.before_request
def before_request():
    auth_module.load_user()
    g.locale = i18n.resolve_locale(request.headers.get("Accept-Language"))
    if request.method in {"POST", "PUT", "PATCH", "DELETE"} and session.get("user_id"):
        if not _is_origin_valid_for_state_change():
            if request.path.startswith("/api/"):
                return jsonify({"success": False, "error": "Origin validation failed"}), 403
            return "Origin validation failed", 403


@app.context_processor
def inject_shell_context():
    locale = getattr(g, "locale", "en")
    return {
        "project_title": db.get_setting("project_title") or db.DEFAULT_PROJECT_TITLE,
        "project_subtitle": db.get_setting("project_subtitle") or db.DEFAULT_PROJECT_SUBTITLE,
        "format_token_count": format_token_count,
        "locale": locale,
        "t": lambda key, **values: i18n.translate(locale, key, **values),
    }
```

- [ ] **Step 4: Replace hard-coded shell/page copy and JS strings with translation keys**

Update `service/templates/base.html`:

```jinja
<html lang="{{ locale }}">
<a href="{{ url_for('leaderboard') }}">{{ t('nav.leaderboard') }}</a>
<a href="{{ url_for('docs_page') }}">{{ t('nav.docs') }}</a>
<a href="{{ url_for('account') }}">{{ t('nav.account') }}</a>
<button type="submit">{{ t('nav.logout') }}</button>
```

Update `service/templates/login.html`:

```jinja
{% block title %}{{ t('login.title') }} | {{ project_title }}{% endblock %}
<label for="username">{{ t('login.username') }}</label>
<label for="password">{{ t('login.password') }}</label>
<button class="btn-primary" type="submit">{{ t('login.submit') }}</button>
```

Update `service/templates/local_admin_login.html`:

```jinja
{% block title %}{{ t('local_admin.title') }} | {{ project_title }}{% endblock %}
<h1 style="margin-top: 0;">{{ t('local_admin.title') }}</h1>
<button class="btn-primary" type="submit">{{ t('local_admin.submit') }}</button>
```

Update `service/templates/leaderboard.html` so JS consumes injected strings instead of hard-coded English:

```jinja
<h1 class="hero-title">{{ t('leaderboard.title') }}</h1>
<p class="muted" data-leaderboard-status>{{ t('leaderboard.loading') }}</p>
<script>
    const leaderboardMessages = {{ {
        "loading": t("leaderboard.loading"),
        "preparing": t("leaderboard.preparing"),
        "failed": t("leaderboard.failed"),
    } | tojson }};
```

Use the injected map in the script:

```javascript
tbody.innerHTML = `<tr><td colspan="7" class="muted">${escapeHtml(leaderboardMessages.preparing)}</td></tr>`;
renderLeaderboardStatus(leaderboardMessages.loading);
renderLeaderboardStatus(leaderboardMessages.failed, true);
```

Update `service/templates/docs.html`:

```jinja
{% block title %}{{ t('docs.title') }} | {{ project_title }}{% endblock %}
<h2 style="margin-top: 0;">{{ t('docs.sidebar_title') }}</h2>
```

Update `service/templates/account.html`:

```jinja
{% block title %}{{ t('account.title') }} | {{ project_title }}{% endblock %}
<h1 class="hero-title">{{ t('account.title') }}</h1>
<button type="button" class="btn-primary" data-account-copy>{{ t('account.copy') }}</button>
<button type="button" data-account-rotate>{{ t('account.rotate') }}</button>
<button class="btn-primary" type="submit">{{ t('account.password_submit') }}</button>
```

Update the account-page JS status messages:

```jinja
<script>
const accountMessages = {{ {
    "copied": t("account.copied"),
    "rotated": t("account.rotated"),
    "password_updated": t("account.password_updated"),
} | tojson }};
</script>
```

Then replace the hard-coded strings in the existing account script:

```javascript
hookKeyMessage.textContent = accountMessages.copied;
hookKeyMessage.textContent = accountMessages.rotated;
passwordMessage.textContent = payload.success ? accountMessages.password_updated : payload.error;
```

Update `service/templates/user_detail.html`:

```jinja
<p class="muted" style="margin-top: 10px;">{{ t('user_detail.title') }} for {{ stats.user.username }} within the selected {{ window_label }} window.</p>
<button type="button" class="timeline-range-button{% if window == 'today' %} is-active{% endif %}" data-user-detail-window-option="today">{{ t('user_detail.window.today') }}</button>
```

Inject the JS-only strings in `service/templates/user_detail.html`:

```jinja
<script>
const userDetailMessages = {{ {
    "loading": t("user_detail.loading"),
    "no_data": t("user_detail.no_data"),
} | tojson }};
</script>
```

Update the admin/system templates with translated titles and top headings:

```jinja
{% block title %}{{ t('settings.title') }} | {{ project_title }}{% endblock %}
<h1 style="margin-top: 0;">{{ t('settings.title') }}</h1>
```

```jinja
{% block title %}{{ t('api_list.title') }} | {{ project_title }}{% endblock %}
<h1 style="margin-top: 0;">{{ t('api_list.title') }}</h1>
```

```jinja
{% block title %}{{ t('admin_users.title') }} | {{ project_title }}{% endblock %}
<h1 class="hero-title">{{ t('admin_users.title') }}</h1>
```

```jinja
{% block title %}{{ t('admin_ldap.title') }} | {{ project_title }}{% endblock %}
<h1 class="hero-title">{{ t('admin_ldap.title') }}</h1>
```

```jinja
{% block title %}{{ t('admin_agents.title') }} | {{ project_title }}{% endblock %}
<h1 class="hero-title">{{ t('admin_agents.title') }}</h1>
```

Translate route-level inline messages in `service/app.py` with the same helper:

```python
error = i18n.translate(g.locale, "login.invalid_credentials")
```

- [ ] **Step 5: Run the focused i18n tests to verify they pass**

Run:

```bash
pytest service/tests/test_i18n.py -q
```

Expected: PASS

- [ ] **Step 6: Commit the translated UI slice**

Run:

```bash
git add service/i18n.py service/tests/test_i18n.py service/app.py service/templates/base.html service/templates/login.html service/templates/local_admin_login.html service/templates/leaderboard.html service/templates/docs.html service/templates/user_detail.html service/templates/settings.html service/templates/api_list.html service/templates/admin_users.html service/templates/admin_ldap.html service/templates/admin_agents.html service/templates/account.html
git commit -m "feat: add browser-language ui translations"
```

## Task 4: Localize Docs Selection with English Fallback

**Files:**

- Modify: `service/tests/test_docs_page.py`
- Modify: `service/app.py`
- Create: `docs/README.zh-CN.md`

- [ ] **Step 1: Add failing docs localization and fallback tests**

Update `service/tests/test_docs_page.py`:

```python
def test_docs_page_prefers_chinese_variant_when_available(auth_session):
    response = auth_session.get("/docs", headers={"Accept-Language": "zh-CN,zh;q=0.9"})

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "TokenLeague 文档" in html
    assert "Token 使用排行榜应用" in html


def test_docs_page_falls_back_to_english_when_localized_file_is_missing(auth_session):
    response = auth_session.get("/docs/HOOKS.md", headers={"Accept-Language": "zh-CN,zh;q=0.9"})

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "TokenLeague Hooks" in html
    assert "automatically track token usage" in html


def test_docs_sidebar_does_not_duplicate_localized_variants(auth_session):
    response = auth_session.get("/docs", headers={"Accept-Language": "zh-CN,zh;q=0.9"})

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "README.zh-CN.md" not in html
    assert html.count('href="/docs/README.md"') == 1
```

- [ ] **Step 2: Run the focused docs tests to verify they fail**

Run:

```bash
pytest service/tests/test_docs_page.py -q
```

Expected: FAIL because docs lookup and sidebar generation still treat all Markdown files as one-language documents.

- [ ] **Step 3: Resolve localized docs by logical path and keep the sidebar de-duplicated**

Add helpers near the docs functions in `service/app.py`:

```python
def _localized_doc_name(filepath: str, locale: str) -> str:
    if locale != "zh-CN":
        return filepath
    path = Path(filepath)
    return str(path.with_name(f"{path.stem}.zh-CN{path.suffix}"))


def _resolve_doc_target(filepath: str, locale: str) -> Path:
    localized_target = DOCS_DIR / _localized_doc_name(filepath, locale)
    if localized_target.exists():
        return localized_target
    return DOCS_DIR / filepath


def _logical_doc_path(filename: str) -> str:
    return filename.replace(".zh-CN.md", ".md")


def _read_doc_title(path: Path) -> str:
    title = path.stem.replace("-", " ").replace("_", " ").title()
    with path.open("r", encoding="utf-8") as handle:
        first_line = handle.readline().strip()
    if first_line.startswith("# "):
        return first_line[2:].strip()
    return title
```

Replace `_get_doc_list()` with locale-aware grouping:

```python
def _get_doc_list(locale: str):
    docs = {}
    for path in sorted(DOCS_DIR.glob("*.md")):
        logical_path = _logical_doc_path(path.name)
        if logical_path in docs:
            continue
        title_source = _resolve_doc_target(logical_path, locale)
        if not title_source.exists():
            title_source = DOCS_DIR / logical_path
        docs[logical_path] = {
            "path": logical_path,
            "title": _read_doc_title(title_source),
        }
    return list(docs.values())
```

Update `docs_page()` to use the resolved locale target:

```python
def docs_page(filepath: str = "README.md"):
    if ".." in filepath or filepath.startswith("/"):
        return "Invalid path", 403
    target = _resolve_doc_target(filepath, g.locale)
    if not target.exists():
        raw_markdown = f"# Not Found\n\nMissing document: {filepath}"
    else:
        raw_markdown = target.read_text(encoding="utf-8")
    return render_template(
        "docs.html",
        doc_list=_get_doc_list(g.locale),
        current_doc=filepath,
        raw_markdown=raw_markdown,
    )
```

- [ ] **Step 4: Add a visible Chinese root docs page**

Create `docs/README.zh-CN.md`:

```markdown
# TokenLeague 文档

TokenLeague 是一个用于跟踪 AI 助手使用量并展示排行榜的 Token 使用统计应用。

## 可用文档

- **[Hooks 指南](HOOKS.md)** - 为 Claude Code 和 Codex CLI 配置统计 hooks

## 快速入口

- **接口列表**: `/api` - 查看所有可用 API 端点
- **排行榜**: `/leaderboard` - 查看 Token 使用排名
- **管理后台**: `/admin/users` - 管理用户

## 当前模板已包含

- Flask 应用基础接线
- Session 登录鉴权
- 设置页
- 文档页
- API 列表页

## 建议你在新项目中先补充

- 项目目标与范围
- 业务模块拆分规则
- 数据表命名约定
- 部署与回滚方式

## 后续可以继续补充

- 领域模型
- 业务 API
- 项目专属页面
- 更多系统集成
```

- [ ] **Step 5: Run the focused docs tests to verify they pass**

Run:

```bash
pytest service/tests/test_docs_page.py -q
```

Expected: PASS

- [ ] **Step 6: Commit the localized docs slice**

Run:

```bash
git add service/tests/test_docs_page.py service/app.py docs/README.zh-CN.md
git commit -m "feat: add localized docs selection"
```

## Task 5: Run Full Verification for the Whole Feature

**Files:**

- Modify only if verification exposes a real regression in one of the files above

- [ ] **Step 1: Run the focused suite that covers access control, account flows, i18n, and docs**

Run:

```bash
pytest service/tests/test_auth_flow.py service/tests/test_api_list_page.py service/tests/test_docs_page.py service/tests/test_i18n.py service/tests/test_token_league.py -q
```

Expected: PASS

- [ ] **Step 2: Run the full service test suite once before declaring the feature complete**

Run:

```bash
pytest service/tests -q
```

Expected: PASS

- [ ] **Step 3: Manually smoke-check the four key browser flows**

Run:

```bash
cd service
python app.py
```

Then verify in the browser:

- login with a normal user and confirm only `Leaderboard`, `Docs`, username menu, and `Logout` are visible
- open `/account`, copy the key, rotate it, and change the password
- confirm `/users/<other_id>`, `/settings`, `/api`, and `/admin/users` return `403` for a normal user
- switch browser language between Chinese and English and confirm the shell and docs content follow the language with English fallback on `HOOKS.md`

- [ ] **Step 4: If the manual smoke check required code changes, commit the final cleanup**

Run only if Step 3 exposed and fixed a real bug:

```bash
git add service/auth.py service/app.py service/i18n.py service/templates/base.html service/templates/account.html service/templates/leaderboard.html service/templates/docs.html service/templates/login.html service/templates/local_admin_login.html service/templates/user_detail.html service/templates/settings.html service/templates/api_list.html service/templates/admin_users.html service/templates/admin_ldap.html service/templates/admin_agents.html service/tests/conftest.py service/tests/test_auth_flow.py service/tests/test_api_list_page.py service/tests/test_docs_page.py service/tests/test_i18n.py service/tests/test_token_league.py docs/README.zh-CN.md
git commit -m "fix: polish account access and i18n flows"
```
