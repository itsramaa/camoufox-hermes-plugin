"""AsyncCamoufox kwargs builder + launcher for guest/persistent modes.

camoufox/playwright are imported lazily so a missing dependency raises
DependencyMissingError at launch, not at plugin import.
"""

from __future__ import annotations

import os
from pathlib import Path

from .config import Settings
from .exceptions import DependencyMissingError
from .models import InstanceStatus, ProxySpec
from .proxy import build_proxy

SCREEN_CONFIG: dict[str, int] = {
    "screen.width": 1366,
    "screen.height": 768,
    "screen.availWidth": 1366,
    "screen.availHeight": 728,
    "screen.availLeft": 0,
    "screen.availTop": 0,
    "window.outerWidth": 1366,
    "window.outerHeight": 720,
    "window.screenX": 0,
    "window.screenY": 0,
}


def _import_camoufox() -> None:
    """Fail closed with a DependencyMissingError when camoufox is absent."""
    if not os.environ.get("XDG_CACHE_HOME"):
        data_cache = Path(__file__).resolve().parents[3] / ".cache"
        if data_cache.is_dir():
            os.environ["XDG_CACHE_HOME"] = str(data_cache)
    try:
        import camoufox  # noqa: F401
    except Exception as exc:  # pragma: no cover - dep-specific
        raise DependencyMissingError(
            "camoufox is not installed in this environment; "
            "add it to the plugin pip_dependencies (Hermes PM installs it)."
        ) from exc


def build_launch_kwargs(
    settings: Settings,
    *,
    proxy_spec: ProxySpec | None,
    headless: bool | str,
    user_data_dir: Path | None,
) -> dict:
    """Camera-fingerprint kwargs mirrored from the verified reference launcher."""
    _import_camoufox()
    from camoufox.addons import DefaultAddons  # type: ignore[import-not-found]

    kwargs: dict = {
        "headless": headless,
        "block_webrtc": True,
        "humanize": 0.3,
        "os": "windows",
        "config": dict(SCREEN_CONFIG),
        "exclude_addons": [DefaultAddons.UBO],
        "i_know_what_im_doing": True,
        "locale": "en-US",
        "enable_cache": True,
        "firefox_user_prefs": {
            "widget.windows.window_occlusion_tracking.enabled": False,
            "dom.min_background_timeout_value": 10,
            "devtools.selfxss.count": 0,
            "devtools.everOpened": False,
            "devtools.debugger.remote-enabled": False,
        },
    }
    if user_data_dir is not None:
        kwargs["persistent_context"] = True
        kwargs["user_data_dir"] = str(user_data_dir)

    proxy = build_proxy(proxy_spec)
    if proxy is not None:
        playwright_proxy = proxy.to_playwright()
        if proxy.session_id and proxy.username is None:
            from .proxy import dataimpulse_username

            playwright_proxy["username"] = dataimpulse_username(
                "user", proxy.session_id, proxy.country or ""
            )
        kwargs["proxy"] = playwright_proxy
        kwargs["geoip"] = True
    return kwargs


async def launch_browser(
    settings: Settings,
    *,
    proxy_spec: ProxySpec | None,
    headless: bool | str,
    user_data_dir: Path | None,
) -> tuple[object, object, Path | None]:
    """Return (manager, browser, temp_dir). *temp_dir* is always None.

    The caller's ``user_data_dir`` is passed through verbatim: guest launches
    pass ``None`` (non-persistent, no ``persistent_context``), persistent
    launches pass the profile dir (``persistent_context=True``).
    """
    import asyncio

    from camoufox.async_api import AsyncCamoufox  # type: ignore[import-not-found]

    kwargs = build_launch_kwargs(
        settings,
        proxy_spec=proxy_spec,
        headless=headless,
        user_data_dir=user_data_dir,
    )
    manager = AsyncCamoufox(**kwargs)
    browser = await asyncio.wait_for(
        manager.__aenter__(), timeout=settings.launch_timeout_seconds
    )
    # Guest isolation comes from the ephemeral non-persistent context; no temp
    # profile dir is created or returned.
    return manager, browser, None
