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
