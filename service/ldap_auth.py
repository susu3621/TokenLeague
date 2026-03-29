from __future__ import annotations

from typing import Any, Callable


LDAPUser = dict[str, str]


class LDAPClientAdapter:
    def __init__(self, settings: dict[str, Any]):
        self._settings = settings
        self._connection = None

    def bind(self, dn: str, password: str) -> bool:
        self.close()
        self._connection = _create_connection(self._settings, dn, password)
        return self._connection.bind()

    def search_users(self, base_dn: str, user_filter: str, attributes: list[str]) -> list[Any]:
        if self._connection is None:
            return []
        self._connection.search(base_dn, user_filter, attributes=attributes)
        return list(self._connection.entries)

    def close(self) -> None:
        if self._connection is None:
            return
        try:
            self._connection.unbind()
        finally:
            self._connection = None


def _create_connection(settings: dict[str, Any], dn: str, password: str):
    from ldap3 import Connection, Server

    server = Server(
        settings["host"],
        port=settings["port"],
        use_ssl=settings.get("use_ssl", False),
        get_info=None,
    )
    connection = Connection(
        server,
        user=dn,
        password=password,
        auto_bind=False,
        raise_exceptions=False,
    )
    if settings.get("start_tls"):
        connection.open()
        connection.start_tls()
    return connection


def _get_client(settings: dict[str, Any], client_factory: Callable[[dict[str, Any]], Any] | None = None):
    factory = client_factory or LDAPClientAdapter
    return factory(settings)


def _coerce_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return _coerce_text(value[0]) if value else ""
    return str(value).strip()


def _read_entry_value(entry: Any, attribute_name: str) -> str:
    if isinstance(entry, dict):
        return _coerce_text(entry.get(attribute_name))

    if hasattr(entry, "entry_attributes_as_dict"):
        values = getattr(entry, "entry_attributes_as_dict", {})
        if isinstance(values, dict) and attribute_name in values:
            return _coerce_text(values.get(attribute_name))

    candidate = getattr(entry, attribute_name, None)
    if hasattr(candidate, "value"):
        return _coerce_text(candidate.value)
    return _coerce_text(candidate)


def _read_entry_dn(entry: Any) -> str:
    if isinstance(entry, dict):
        return _coerce_text(entry.get("dn"))
    return _coerce_text(getattr(entry, "entry_dn", None) or getattr(entry, "dn", None))


def _normalize_user(entry: Any, settings: dict[str, Any]) -> LDAPUser | None:
    username = _read_entry_value(entry, settings["username_attribute"])
    ldap_dn = _read_entry_dn(entry)
    if not username or not ldap_dn:
        return None

    display_name = _read_entry_value(entry, settings["display_name_attribute"]) or username
    return {
        "username": username,
        "display_name": display_name,
        "ldap_dn": ldap_dn,
    }


def _build_user_filter(settings: dict[str, Any], username: str | None = None) -> str:
    template = settings.get("user_filter") or f"({settings['username_attribute']}={{username}})"
    if username is None:
        return template
    return template.replace("{username}", username)


def validate_settings(settings: dict[str, Any], *, require_bind: bool) -> list[str]:
    missing = []
    required_fields = ["host", "base_dn", "username_attribute", "display_name_attribute", "user_filter"]
    if require_bind:
        required_fields.extend(["bind_dn", "bind_password"])

    for field in required_fields:
        if not str(settings.get(field) or "").strip():
            missing.append(field)

    if not settings.get("port"):
        missing.append("port")
    if settings.get("use_ssl") and settings.get("start_tls"):
        missing.append("transport")
    return missing


def test_connection(
    settings: dict[str, Any],
    *,
    client_factory: Callable[[dict[str, Any]], Any] | None = None,
) -> tuple[bool, str | None]:
    missing = validate_settings(settings, require_bind=True)
    if missing:
        return False, f"Missing LDAP settings: {', '.join(missing)}"

    client = _get_client(settings, client_factory)
    try:
        if not client.bind(settings["bind_dn"], settings["bind_password"]):
            return False, "LDAP bind failed"
        return True, None
    except Exception as exc:  # pragma: no cover - defensive runtime handling
        return False, str(exc)
    finally:
        if hasattr(client, "close"):
            client.close()


def authenticate_user(
    settings: dict[str, Any],
    username: str,
    password: str,
    *,
    client_factory: Callable[[dict[str, Any]], Any] | None = None,
) -> LDAPUser | None:
    if not str(username or "").strip() or not str(password or ""):
        return None

    missing = validate_settings(settings, require_bind=True)
    if missing:
        return None

    client = _get_client(settings, client_factory)
    try:
        if not client.bind(settings["bind_dn"], settings["bind_password"]):
            return None

        entries = client.search_users(
            settings["base_dn"],
            _build_user_filter(settings, username.strip()),
            [settings["username_attribute"], settings["display_name_attribute"]],
        )
        if not entries:
            return None

        user = _normalize_user(entries[0], settings)
        if not user:
            return None

        if not client.bind(user["ldap_dn"], password):
            return None
        return user
    finally:
        if hasattr(client, "close"):
            client.close()


def list_users(
    settings: dict[str, Any],
    *,
    client_factory: Callable[[dict[str, Any]], Any] | None = None,
) -> list[LDAPUser]:
    missing = validate_settings(settings, require_bind=True)
    if missing:
        return []

    client = _get_client(settings, client_factory)
    try:
        if not client.bind(settings["bind_dn"], settings["bind_password"]):
            return []

        users: list[LDAPUser] = []
        for entry in client.search_users(
            settings["base_dn"],
            _build_user_filter(settings),
            [settings["username_attribute"], settings["display_name_attribute"]],
        ):
            normalized = _normalize_user(entry, settings)
            if normalized:
                users.append(normalized)
        return users
    finally:
        if hasattr(client, "close"):
            client.close()
