"""Smoke tests for InstanceRegistry (browser mocked) and SSE frame shape.

Run with the plugin root on sys.path; ``core`` is importable as a top-level
package here because the tests chdir into the plugin dir.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent
if str(_PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_ROOT))

# Alias the plugin's package importable under both names for tests.
from core import instance_registry as registry_mod  # noqa: E402
from core.config import Settings  # noqa: E402
from core.exceptions import (
    MaxConcurrencyReachedError,
    ProfileLockedError,
    InstanceNotFoundError,
)  # noqa: E402

reg_mod = registry_mod
# Patch the wire function so no real browser launches.
_WIRE = registry_mod.InstanceRegistry._wire_instance


async def _fake_wire(self, inst, *, start_url, proxy, user_data_dir):
    class _Page:
        def __init__(self, url):
            self.url = url or "about:blank"

        async def screenshot(self, **_):
            return b"\xff\xd8\xff\xe0JPEG\xff\xd9"

        async def title(self):
            return "title"

        async def goto(self, url, **_):
            self.url = url

        async def close(self):
            pass

    class _Browser:
        process = None

    inst.status = registry_mod.InstanceStatus.RUNNING
    inst.page = _Page(start_url)
    inst.context = _Browser()
    inst._browser = inst.context
    inst.last_active = inst.created_at


@pytest.fixture(autouse=True)
def _mock_wire(monkeypatch):
    monkeypatch.setattr(registry_mod.InstanceRegistry, "_wire_instance", _fake_wire)


def _settings(tmp_path, **kw):
    s = Settings(
        profile_root=str(tmp_path / "profiles"),
        max_guest_concurrency=2,
        reaper_interval_seconds=0,
    )
    for k, v in kw.items():
        setattr(s, k, v)
    return s


@pytest.mark.asyncio
async def test_guest_concurrency_bounded(tmp_path):
    reg = registry_mod.InstanceRegistry(_settings(tmp_path))
    a = await reg.launch(
        mode="guest",
        profile=None,
        start_url="https://a",
        proxy=None,
        headless=None,
        ttl_seconds=None,
    )
    b = await reg.launch(
        mode="guest",
        profile=None,
        start_url="https://b",
        proxy=None,
        headless=None,
        ttl_seconds=None,
    )
    with pytest.raises(MaxConcurrencyReachedError):
        await reg.launch(
            mode="guest",
            profile=None,
            start_url="x",
            proxy=None,
            headless=None,
            ttl_seconds=None,
        )
    assert reg.stats()["guests_in_use"] == 2
    assert await reg.kill(a.id) is True
    assert reg.stats()["guests_in_use"] == 1


@pytest.mark.asyncio
async def test_persistent_profile_lock(tmp_path):
    reg = registry_mod.InstanceRegistry(_settings(tmp_path))
    p1 = await reg.launch(
        mode="persistent",
        profile="work",
        start_url=None,
        proxy=None,
        headless=None,
        ttl_seconds=None,
    )
    with pytest.raises(ProfileLockedError):
        await reg.launch(
            mode="persistent",
            profile="work",
            start_url=None,
            proxy=None,
            headless=None,
            ttl_seconds=None,
        )
    await reg.kill(p1.id)
    # after kill the profile is re-usable
    p2 = await reg.launch(
        mode="persistent",
        profile="work",
        start_url=None,
        proxy=None,
        headless=None,
        ttl_seconds=None,
    )
    await reg.kill(p2.id)


@pytest.mark.asyncio
async def test_missing_instance_not_found(tmp_path):
    reg = registry_mod.InstanceRegistry(_settings(tmp_path))
    assert reg.get("nope") is None
    assert await reg.kill("nope") is False


@pytest.mark.asyncio
async def test_sse_frame_shape(tmp_path, monkeypatch):
    """sse_stream emits a frame SSE for a live instance then closes cleanly."""
    from core import screencaster

    reg = registry_mod.InstanceRegistry(_settings(tmp_path))
    monkeypatch.setattr(registry_mod, "REGISTRY", reg)
    # sse_stream looks up REGISTRY at module import time; rebind it.
    monkeypatch.setattr(screencaster, "REGISTRY", reg)

    inst = await reg.launch(
        mode="guest",
        profile=None,
        start_url="https://x",
        proxy=None,
        headless=None,
        ttl_seconds=None,
    )

    import asyncio

    it = screencaster.sse_stream(inst.id, fps=20.0, quality=50)
    first = await it.__anext__()
    assert first.startswith("event: frame\n")
    assert "data:image/jpeg;base64," in first
    # Kill the instance; next poll should emit status closed.
    await reg.kill(inst.id)
    closed = await it.__anext__()
    assert "event: status" in closed or "closed" in closed
    await it.aclose()


def test_registry_singleton_exists():
    assert hasattr(registry_mod, "REGISTRY")
