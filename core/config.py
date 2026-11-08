"""Typed settings with plugin-scoped overrides.

Defaults live here; ``from_config(ctx)`` bridges the Hermes plugin settings
namespace onto a plain dataclass without any direct dependency on the host.
"""

from __future__ import annotations

from dataclasses import dataclass

from typing import Any


@dataclass(frozen=True)
class Settings:
    """Runtime settings for one camoufox plugin instance."""

    max_guest_concurrency: int = 3
    guest_ttl_seconds: int = 15 * 60
    persistent_ttl_seconds: int = 60 * 60
    default_fps: float = 1.5
    default_jpeg_quality: int = 50
    default_headless: bool = True
    launch_timeout_seconds: float = 60.0
    reaper_interval_seconds: float = 30.0
    profile_root: str = ""  # empty => resolved from HERMES_HOME at runtime

    @classmethod
    def from_config(cls, ctx: Any, root_hint: str | None = None) -> "Settings":
        """Read operator overrides from the plugin context when available."""
        if ctx is None:
            profile_root = root_hint or "profiles"
            return cls(profile_root=profile_root)

        def _get(key: str, default: Any) -> Any:
            try:
                value = ctx.get_config(key, default)
            except Exception:
                return default
            return default if value is None else value

        profile_root = str(_get("profile_root", root_hint or "profiles"))
        return cls(
            max_guest_concurrency=int(_get("max_guest_concurrency", 3)),
            guest_ttl_seconds=int(_get("guest_ttl_seconds", 15 * 60)),
            persistent_ttl_seconds=int(_get("persistent_ttl_seconds", 60 * 60)),
            default_fps=float(_get("default_fps", 1.5)),
            default_jpeg_quality=int(_get("default_jpeg_quality", 50)),
            default_headless=bool(_get("default_headless", True)),
            launch_timeout_seconds=float(_get("launch_timeout_seconds", 60.0)),
            reaper_interval_seconds=float(_get("reaper_interval_seconds", 30.0)),
            profile_root=profile_root,
        )


SETTINGS = Settings()
