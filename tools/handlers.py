"""Tool handlers and registration for the camoufox plugin."""

from __future__ import annotations

import logging
from typing import Any

from tools.registry import tool_error, tool_result

from ..core.exceptions import CamoufoxPluginError, ProfileLockedError
from ..core.instance_registry import REGISTRY
from ..core.models import LaunchRequest, ProxySpec
from .schemas import (
    CAMOUFOX_ACTION_SCHEMA,
    CAMOUFOX_CLOSE_SCHEMA,
    CAMOUFOX_EXTRACT_SCHEMA,
    CAMOUFOX_NAVIGATE_SCHEMA,
)

logger = logging.getLogger(__name__)


def _mask_password(value: str | None) -> str | None:
    if not value:
        return None
    return "***"


def _mask_username(value: str | None) -> str | None:
    if not value:
        return None
    if len(value) <= 4:
        return "***"
    return value[:2] + "***" + value[-2:]


def _safe_proxy_log(proxy: ProxySpec | None) -> dict[str, str | None] | None:
    if proxy is None:
        return None
    return {
        "server": proxy.server,
        "username": _mask_username(proxy.username),
        "password": _mask_password(proxy.password),
        "country": proxy.country,
        "session_id": proxy.session_id,
    }


def _proxy_from_args(args: dict) -> ProxySpec | None:
    raw = args.get("proxy")
    if not isinstance(raw, dict) or not raw.get("server"):
        return None
    return ProxySpec(
        server=str(raw["server"]),
        username=raw.get("username"),
        password=raw.get("password"),
        bypass=raw.get("bypass"),
        country=raw.get("country"),
        session_id=raw.get("session_id"),
    )


async def handle_camoufox_navigate(args: dict, **kwargs: Any) -> str:
    """Launch a browser + navigate. Returns instance_id."""
    del kwargs
    try:
        proxy = _proxy_from_args(args)
        logger.debug(
            "camoufox: navigate mode=%s profile=%s url=%s proxy=%s",
            args.get("mode", "guest"),
            args.get("profile"),
            args.get("url"),
            _safe_proxy_log(proxy),
        )
        request = LaunchRequest.from_dict(
            {
                "mode": args.get("mode", "guest"),
                "profile": args.get("profile"),
                "url": args.get("url"),
                "proxy": proxy,
                "headless": args.get("headless"),
                "ttl_seconds": args.get("ttl_seconds"),
            }
        )
        inst = await REGISTRY.launch(
            mode=request.mode,
            profile=request.profile,
            start_url=request.url,
            proxy=request.proxy,
            headless=request.headless,
            ttl_seconds=request.ttl_seconds,
        )
        snap = await inst.snapshot()
        return tool_result({"instance_id": inst.id, **snap.to_dict()})
    except (ProfileLockedError, CamoufoxPluginError) as exc:
        return tool_error(str(exc), status=exc.status_code)
    except ValueError as exc:
        return tool_error(str(exc))


async def handle_camoufox_action(args: dict, **kwargs: Any) -> str:
    """Perform a page action on an instance."""
    del kwargs
    instance_id = args.get("instance_id")
    if not isinstance(instance_id, str) or not instance_id:
        return tool_error("instance_id is required")
    action = args.get("action")
    inst = REGISTRY.get(instance_id)
    if inst is None:
        return tool_error(f"instance {instance_id!r} not found", status=404)
    page = inst.page
    if page is None:
        return tool_error(f"instance {instance_id!r} has no active page", status=503)
    try:
        inst.touch()
        selector = args.get("selector")
        text = args.get("text")
        value = args.get("value")
        if action == "click":
            await page.click(selector)
        elif action == "fill":
            await page.fill(selector, text or "")
        elif action == "type":
            await page.type(selector, text or "")
        elif action == "hover":
            await page.hover(selector)
        elif action == "scroll":
            await page.mouse.wheel(0, int(value or 500))
        elif action == "evaluate":
            await page.evaluate(args.get("script") or "document.title")
        else:
            return tool_error(f"unknown action {action!r}")
        return tool_result({"instance_id": instance_id, "action": action, "ok": True})
    except Exception as exc:
        return tool_error(f"action {action!r} failed: {exc}")


async def handle_camoufox_extract(args: dict, **kwargs: Any) -> str:
    """Extract page content."""
    del kwargs
    instance_id = args.get("instance_id")
    if not isinstance(instance_id, str) or not instance_id:
        return tool_error("instance_id is required")
    inst = REGISTRY.get(instance_id)
    if inst is None:
        return tool_error(f"instance {instance_id!r} not found", status=404)
    page = inst.page
    if page is None:
        return tool_error(f"instance {instance_id!r} has no active page", status=503)
    kind = args.get("kind", "text")
    selector = args.get("selector")
    try:
        inst.touch()
        if kind == "title":
            payload = {"instance_id": instance_id, "title": await inst.title()}
        elif kind == "url":
            payload = {"instance_id": instance_id, "url": await inst.current_url()}
        elif kind == "html":
            payload = {"instance_id": instance_id, "html": await page.content()}
        elif kind == "screenshot":
            import base64 as _b64

            jpeg = await inst.capture_jpeg(80)
            payload = {
                "instance_id": instance_id,
                "image": f"data:image/jpeg;base64,{_b64.b64encode(jpeg).decode()}",
            }
        else:  # text
            if selector:
                payload = {
                    "instance_id": instance_id,
                    "text": await page.locator(selector).text_content(),
                }
            else:
                payload = {
                    "instance_id": instance_id,
                    "text": await page.inner_text("body"),
                }
        return tool_result(payload)
    except Exception as exc:
        return tool_error(f"extract failed: {exc}")


async def handle_camoufox_close(args: dict, **kwargs: Any) -> str:
    """Close an instance."""
    del kwargs
    instance_id = args.get("instance_id")
    if not isinstance(instance_id, str) or not instance_id:
        return tool_error("instance_id is required")
    ok = await REGISTRY.kill(instance_id)
    if not ok:
        return tool_error(f"instance {instance_id!r} not found", status=404)
    return tool_result({"instance_id": instance_id, "closed": True})


__all__ = ["register_tools"]

_TOOLS = [
    (
        "camoufox_navigate",
        CAMOUFOX_NAVIGATE_SCHEMA,
        handle_camoufox_navigate,
        "Launch a Camoufox browser and navigate to a URL.",
    ),
    (
        "camoufox_action",
        CAMOUFOX_ACTION_SCHEMA,
        handle_camoufox_action,
        "Perform a page action (click/fill/type/hover/scroll/evaluate).",
    ),
    (
        "camoufox_extract",
        CAMOUFOX_EXTRACT_SCHEMA,
        handle_camoufox_extract,
        "Extract title/url/html/text/screenshot from a page.",
    ),
    (
        "camoufox_close",
        CAMOUFOX_CLOSE_SCHEMA,
        handle_camoufox_close,
        "Close a Camoufox instance and release its resources.",
    ),
]


def register_tools(ctx: Any) -> None:
    for name, schema, handler, description in _TOOLS:
        ctx.register_tool(
            name=name,
            toolset="camoufox",
            schema=schema,
            handler=handler,
            is_async=True,
            description=description,
        )
    logger.debug("camoufox: registered %d tools", len(_TOOLS))
