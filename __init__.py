"""Camoufox plugin entry point.

Anti-detect browser automation via Camoufox (Playwright-compatible):
guest + persistent profiles, proxy, background reaper, model tools,
dashboard API and a live SSE screencast UI.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def register(ctx: Any) -> None:
    """Register tools and the background reaper for this plugin instance."""
    from .core import instance_registry as _ir
    from .core.config import Settings
    from .tools import register_tools

    register_tools(ctx)

    settings = Settings.from_config(ctx, root_hint=str(Path(__file__).parent))
    _ir.REGISTRY = _ir.InstanceRegistry(settings)

    try:
        task = ctx.spawn_task(
            _ir.REGISTRY.reaper(), name=f"plugin:{ctx.plugin_id}:reaper"
        )
    except RuntimeError as exc:
        # spawn_task requires a running loop (CLI register has none).
        logger.debug("camoufox: reaper not started (%s)", exc)

    def _shutdown() -> None:
        reg = _ir.REGISTRY
        if reg._instances:  # noqa: SLF001 - teardown from another module
            loop = _get_loop()
            if loop is not None:
                loop.create_task(reg.shutdown_all())

    ctx.on_unload(_shutdown)
    logger.debug("camoufox: registered %d tools", 4)


def _get_loop() -> Any:
    """Best-effort running loop for the unload-time shutdown task."""
    import asyncio

    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None
