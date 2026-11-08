"""Proxy configuration and the DataImpulse username-embedding syntax.

DataImpulse encodes parameters in the username: ``login__cr.au;sessid.X`` —
two-underscore after the login, key/value joined by a dot, parameters
separated by ``;``. Mirrors ``.example/tabi-x-seek/bansos/browser.py``.
"""

from __future__ import annotations

import secrets
from .models import ProxySpec


def new_session_id() -> str:
    """Alphanumeric only — '.' and ';' are the DataImpulse separators."""
    return "acc" + secrets.token_hex(8)


def dataimpulse_username(user: str, session_id: str, country: str = "") -> str:
    params: list[str] = []
    if country:
        params.append(f"cr.{country}")
    params.append(f"sessid.{session_id}")
    return f"{user}__{';'.join(params)}"


def build_proxy(spec: ProxySpec | None) -> ProxySpec | None:
    """Normalize a ProxySpec into Playwright-dict-compatible fields.

    When a DataImpulse username (contains ``__``) has no explicit session_id,
    mint one so a stable IP can be requested.
    """
    if spec is None or not spec.server:
        return None
    result = ProxySpec(
        server=spec.server,
        username=spec.username,
        password=spec.password,
        bypass=spec.bypass or "localhost,127.0.0.1",
        country=spec.country,
        session_id=spec.session_id,
    )
    if result.username and "__" in result.username and not result.session_id:
        result.session_id = new_session_id()
        if result.country:
            # keep the raw user part before ``__`` intact and re-embed parameters
            base_user = result.username.split("__", 1)[0]
            result.username = dataimpulse_username(
                base_user, result.session_id, result.country
            )
    return result
