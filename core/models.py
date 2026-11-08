"""Data models and instance snapshots.

Pydantic is optional at import time: the dashboard/tools run fine with the
plain dataclasses below when pydantic is not present in the process; the API
layer can wrap them if/when pydantic is available.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class InstanceStatus(str, Enum):
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    CLOSED = "closed"
    ERROR = "error"


@dataclass(slots=True)
class ProxySpec:
    server: str
    username: str | None = None
    password: str | None = None
    bypass: str | None = None
    country: str | None = None
    session_id: str | None = None

    def to_playwright(self) -> dict[str, str]:
        data: dict[str, str] = {"server": self.server}
        if self.username:
            data["username"] = self.username
        if self.password:
            data["password"] = self.password
        if self.bypass:
            data["bypass"] = self.bypass
        return data


@dataclass(slots=True)
class InstanceSnapshot:
    id: str
    mode: str
    profile: str | None
    status: str
    created_at: float
    last_active: float
    proxy_label: str | None
    url: str | None
    title: str | None
    headless: bool
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class LaunchRequest:
    mode: str = "guest"
    profile: str | None = None
    url: str | None = None
    proxy: ProxySpec | None = None
    headless: bool | None = None
    ttl_seconds: int | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "LaunchRequest":
        data = data or {}
        proxy_raw = data.get("proxy")
        proxy = None
        if isinstance(proxy_raw, dict) and proxy_raw.get("server"):
            proxy = ProxySpec(
                server=str(proxy_raw["server"]),
                username=proxy_raw.get("username"),
                password=proxy_raw.get("password"),
                bypass=proxy_raw.get("bypass"),
                country=proxy_raw.get("country"),
                session_id=proxy_raw.get("session_id"),
            )
        return cls(
            mode=str(data.get("mode") or "guest"),
            profile=data.get("profile"),
            url=data.get("url"),
            proxy=proxy,
            headless=data.get("headless"),
            ttl_seconds=int(data["ttl_seconds"]) if data.get("ttl_seconds") else None,
        )


def now_ts() -> float:
    return time.time()
