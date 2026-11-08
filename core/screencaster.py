"""Server-Sent-Events screencaster for live browser frames.

Yields SSE frames: ``event: frame`` with a base64 JPEG + url/title/status/timestamp,
then ``event: status`` ``{"status":"closed"}`` when the instance dies. A heartbeat
comment keeps the connection alive across idle proxies. Swallows
``asyncio.CancelledError`` on client disconnect.
"""

from __future__ import annotations

import asyncio
import base64
import json
import time
from typing import AsyncIterator

from .exceptions import InstanceNotFoundError
from .instance_registry import REGISTRY


def _format_sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


async def sse_stream(
    instance_id: str, fps: float = 1.5, quality: int = 50
) -> AsyncIterator[str]:
    """Async iterator yielding SSE strings for one instance."""
    interval = max(0.5, 1.0 / max(0.5, fps))
    last_heartbeat = time.monotonic()
    try:
        while True:
            inst = REGISTRY.get(instance_id)
            if inst is None:
                yield _format_sse(
                    "status", {"status": "closed", "error": "instance not found"}
                )
                return
            if inst.status.value in {"closed", "error"}:
                yield _format_sse("status", {"status": inst.status.value})
                return
            try:
                jpeg = await inst.capture_jpeg(quality)
                b64 = base64.b64encode(jpeg).decode("ascii")
                frame = {
                    "instance_id": inst.id,
                    "image": f"data:image/jpeg;base64,{b64}",
                    "url": await inst.current_url(),
                    "title": await inst.title(),
                    "status": inst.status.value,
                    "timestamp": time.time(),
                }
                yield _format_sse("frame", frame)
            except asyncio.CancelledError:
                return
            except Exception as exc:
                yield _format_sse("status", {"status": "error", "error": str(exc)})
                return
            now = time.monotonic()
            if now - last_heartbeat >= 15:
                yield ": heartbeat\n\n"
                last_heartbeat = now
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        # Client disconnect: swallow and stop cleanly.
        return
