"""Instance registry: launch/get/list/kill/shutdown_all/stats + Instance.

This module exposes the ``REGISTRY`` singleton shared by the plugin tools and
the standalone dashboard API (they resolve the same ``core.instance_registry``
module object via the ``core`` sys.modules bridge).
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import uuid
from pathlib import Path

from .config import SETTINGS, Settings
from .exceptions import (
    DependencyMissingError,
    InstanceNotFoundError,
    MaxConcurrencyReachedError,
    ProfileLockedError,
)
from .lock_manager import ProfileLockManager
from .models import InstanceSnapshot, InstanceStatus, ProxySpec, now_ts

logger = logging.getLogger(__name__)


def _import_psutil():
    try:
        import psutil  # type: ignore[import-not-found]

        return psutil
    except Exception:  # pragma: no cover - optional at import
        return None


class Instance:
    """One live browser session (page-level handle)."""

    def __init__(
        self,
        *,
        instance_id: str,
        mode: str,
        profile: str | None,
        proxy_label: str | None,
        headless: bool | str,
        ttl_seconds: int,
        temp_dir: Path | None,
        lock_manager: ProfileLockManager | None,
    ) -> None:
        self.id = instance_id
        self.mode = mode
        self.profile = profile
        self.proxy_label = proxy_label
        self.headless = headless
        self.ttl_seconds = ttl_seconds
        self._temp_dir = temp_dir
        self._lock_manager = lock_manager
        self.status = InstanceStatus.STARTING
        self.created_at = now_ts()
        self.last_active = self.created_at
        self.error: str | None = None
        self.page = None
        self.context = None
        self._manager = None
        self._browser = None
        self._pid: int | None = None

    def touch(self) -> None:
        self.last_active = now_ts()

    async def title(self) -> str | None:
        if self.page is None:
            return None
        try:
            return await self.page.title()
        except Exception:
            return None

    async def current_url(self) -> str | None:
        if self.page is None:
            return None
        try:
            url = getattr(self.page, "url", None)
            return str(url) if url else None
        except Exception:
            return None

    async def capture_jpeg(self, quality: int) -> bytes:
        self.touch()
        if self.page is None:
            raise InstanceNotFoundError(f"instance {self.id} has no active page")
        # No PIL: Playwright returns JPEG bytes directly.
        return await self.page.screenshot(
            type="jpeg", quality=max(1, min(100, quality))
        )

    async def goto(self, url: str, *, timeout_ms: int = 30_000) -> None:
        self.touch()
        if self.page is None:
            raise InstanceNotFoundError(f"instance {self.id} has no active page")
        await self.page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)

    async def snapshot(self) -> InstanceSnapshot:
        return InstanceSnapshot(
            id=self.id,
            mode=self.mode,
            profile=self.profile,
            status=self.status.value
            if isinstance(self.status, InstanceStatus)
            else str(self.status),
            created_at=self.created_at,
            last_active=self.last_active,
            proxy_label=self.proxy_label,
            url=await self.current_url(),
            title=await self.title(),
            headless=bool(self.headless),
            error=self.error,
        )

    async def _kill_process_tree(self) -> None:
        psutil = _import_psutil()
        if psutil is None or self._pid is None:
            return
        try:
            proc = psutil.Process(self._pid)
            children = proc.children(recursive=True)
            for child in children:
                try:
                    child.kill()
                except Exception:
                    logger.debug("camoufox: child kill failed pid=%s", child.pid)
            proc.kill()
            psutil.wait_procs([proc, *children], timeout=3)
        except Exception:
            logger.debug("camoufox: process-tree kill failed for %s", self.id)

    async def close(self) -> None:
        if self.status in {InstanceStatus.STOPPING, InstanceStatus.CLOSED}:
            return
        self.status = InstanceStatus.STOPPING
        try:
            if self.page is not None:
                try:
                    await self.page.close()
                except Exception:
                    logger.debug("camoufox: page.close failed for %s", self.id)
            if self.context is not None and self.context is not self._browser:
                try:
                    await self.context.close()
                except Exception:
                    logger.debug("camoufox: context.close failed for %s", self.id)
            if self._browser is not None:
                try:
                    await self._browser.close()
                except Exception:
                    logger.debug("camoufox: browser.close failed for %s", self.id)
            if self._manager is not None:
                try:
                    await self._manager.__aexit__(None, None, None)
                except Exception:
                    logger.debug("camoufox: manager.__aexit__ failed for %s", self.id)
            await self._kill_process_tree()
        finally:
            if self._lock_manager is not None and self.profile:
                try:
                    self._lock_manager.release_disk(self.profile)
                except Exception:
                    logger.debug("camoufox: lock release failed for %s", self.profile)
            if self._temp_dir is not None:
                shutil.rmtree(self._temp_dir, ignore_errors=True)
            self.page = None
            self.context = None
            self._browser = None
            self._manager = None
            self.status = InstanceStatus.CLOSED


class InstanceRegistry:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or SETTINGS
        self._instances: dict[str, Instance] = {}
        self._guest_in_use = 0
        self._profile_locks: dict[str, asyncio.Lock] = {}
        self._lock_manager = ProfileLockManager(self._profiles_dir())
        self._reaper_task: asyncio.Task[None] | None = None

    def _profiles_dir(self) -> Path:
        # Anchor profile data to HERMES_HOME (Docker + per-profile gateways).
        hermes_home = os.environ.get("HERMES_HOME", "").strip()
        if hermes_home:
            base_home = Path(hermes_home).expanduser()
        else:
            base_home = Path.home() / ".hermes"

        configured = (self._settings.profile_root or "").strip()
        if configured:
            root = Path(configured).expanduser()
            if not root.is_absolute():
                root = base_home / root
        else:
            root = base_home / "camoufox" / "profiles"

        hermes_profile = os.environ.get("HERMES_PROFILE") or os.environ.get("HERMES_PROFILE_ID")
        if hermes_profile and hermes_profile != "default":
            return root / hermes_profile
        return root

    def _profile_lock(self, profile: str) -> asyncio.Lock:
        return self._profile_locks.setdefault(profile, asyncio.Lock())

    def get(self, instance_id: str) -> Instance | None:
        return self._instances.get(instance_id)

    def list(self) -> list[dict]:
        items: list[dict] = []
        for inst in self._instances.values():
            items.append(
                {
                    "id": inst.id,
                    "mode": inst.mode,
                    "profile": inst.profile,
                    "status": inst.status.value,
                    "created_at": inst.created_at,
                    "last_active": inst.last_active,
                    "proxy_label": inst.proxy_label,
                    "url": getattr(inst.page, "url", None) if inst.page else None,
                    "headless": bool(inst.headless),
                    "error": inst.error,
                }
            )
        return items

    def stats(self) -> dict:
        values = list(self._instances.values())
        return {
            "total": len(values),
            "running": sum(1 for i in values if i.status == InstanceStatus.RUNNING),
            "guests": sum(1 for i in values if i.mode == "guest"),
            "persistent": sum(1 for i in values if i.mode == "persistent"),
            "guests_in_use": self._guest_in_use,
            "max_guest_concurrency": self._settings.max_guest_concurrency,
        }

    async def launch(
        self,
        *,
        mode: str,
        profile: str | None,
        start_url: str | None,
        proxy: ProxySpec | None,
        headless: bool | None,
        ttl_seconds: int | None,
    ) -> Instance:
        if mode not in {"guest", "persistent"}:
            raise ValueError(f"mode must be 'guest' or 'persistent', got {mode!r}")
        resolved_headless: bool | str = (
            self._settings.default_headless if headless is None else headless
        )
        proxy_label = proxy.server if proxy else None

        if mode == "persistent":
            if not profile:
                raise ValueError("persistent mode requires profile")
            ttl = ttl_seconds or self._settings.persistent_ttl_seconds
            return await self._launch_persistent(
                profile, start_url, proxy, resolved_headless, ttl, proxy_label
            )

        if self._guest_in_use >= self._settings.max_guest_concurrency:
            raise MaxConcurrencyReachedError(
                f"guest concurrency limit reached ({self._settings.max_guest_concurrency})"
            )
        self._guest_in_use += 1
        try:
            ttl = ttl_seconds or self._settings.guest_ttl_seconds
            return await self._launch_guest(
                start_url, proxy, resolved_headless, ttl, proxy_label
            )
        except Exception:
            self._guest_in_use -= 1
            raise

    async def _launch_guest(
        self,
        start_url: str | None,
        proxy: ProxySpec | None,
        headless: bool | str,
        ttl: int,
        proxy_label: str | None,
    ) -> Instance:
        instance_id = uuid.uuid4().hex[:12]
        inst = Instance(
            instance_id=instance_id,
            mode="guest",
            profile=None,
            proxy_label=proxy_label,
            headless=headless,
            ttl_seconds=ttl,
            temp_dir=None,
            lock_manager=None,
        )
        self._instances[instance_id] = inst
        try:
            await self._wire_instance(
                inst, start_url=start_url, proxy=proxy, user_data_dir=None
            )
        except Exception:
            self._instances.pop(instance_id, None)
            raise
        return inst

    async def _launch_persistent(
        self,
        profile: str,
        start_url: str | None,
        proxy: ProxySpec | None,
        headless: bool | str,
        ttl: int,
        proxy_label: str | None,
    ) -> Instance:
        async with self._profile_lock(profile):
            if self._active_persistent(profile):
                raise ProfileLockedError(f"profile {profile!r} is already in use")
            if self._lock_manager.is_locked_on_disk(profile):
                raise ProfileLockedError(f"profile {profile!r} lock is held on disk")
            instance_id = uuid.uuid4().hex[:12]
            inst = Instance(
                instance_id=instance_id,
                mode="persistent",
                profile=profile,
                proxy_label=proxy_label,
                headless=headless,
                ttl_seconds=ttl,
                temp_dir=None,
                lock_manager=self._lock_manager,
            )
            self._instances[instance_id] = inst
            user_dir = self._profiles_dir() / profile
            user_dir.mkdir(parents=True, exist_ok=True)
            self._lock_manager.acquire_disk(profile)
            try:
                await self._wire_instance(
                    inst, start_url=start_url, proxy=proxy, user_data_dir=user_dir
                )
            except Exception:
                self._lock_manager.release_disk(profile)
                self._instances.pop(instance_id, None)
                raise
            return inst

    def _active_persistent(self, profile: str) -> bool:
        return any(
            i.mode == "persistent"
            and i.profile == profile
            and i.status not in {InstanceStatus.CLOSED, InstanceStatus.ERROR}
            for i in self._instances.values()
        )

    async def _wire_instance(
        self,
        inst: Instance,
        *,
        start_url: str | None,
        proxy: ProxySpec | None,
        user_data_dir: Path | None,
    ) -> None:
        from .browser_factory import launch_browser

        inst.status = InstanceStatus.STARTING
        try:
            manager, browser, temp_dir = await launch_browser(
                self._settings,
                proxy_spec=proxy,
                headless=inst.headless,
                user_data_dir=user_data_dir,
            )
            inst._manager = manager
            inst._browser = browser
            inst._temp_dir = temp_dir
            try:
                proc = getattr(browser, "process", None)
                inst._pid = proc.pid if proc else None
            except Exception:
                inst._pid = None
            # Persistent Camoufox returns a BrowserContext; guest returns a
            # Browser. Branch on capability so a mismatched flag can't crash
            # with AttributeError on ``new_context``.
            if hasattr(browser, "new_context"):
                context = await browser.new_context()
                page = await context.new_page()
            else:
                context = browser
                page = await context.new_page()
            inst.context = context
            inst.page = page
            inst.status = InstanceStatus.RUNNING
            inst.touch()
            if start_url:
                await inst.goto(start_url)
        except DependencyMissingError as exc:
            inst.status = InstanceStatus.ERROR
            inst.error = "camoufox dependency missing"
            await inst.close()
            raise DependencyMissingError(str(exc)) from exc
        except (ProfileLockedError, MaxConcurrencyReachedError):
            inst.status = InstanceStatus.ERROR
            await inst.close()
            raise
        except Exception as exc:
            inst.status = InstanceStatus.ERROR
            inst.error = f"{type(exc).__name__}: {exc}"
            await inst.close()
            raise

    async def kill(self, instance_id: str) -> bool:
        inst = self._instances.get(instance_id)
        if inst is None:
            return False
        was_guest = inst.mode == "guest"
        try:
            await inst.close()
        finally:
            self._instances.pop(instance_id, None)
            if was_guest and self._guest_in_use > 0:
                self._guest_in_use -= 1
        return True

    async def shutdown_all(self) -> None:
        for instance_id in list(self._instances):
            try:
                await self.kill(instance_id)
            except Exception:
                logger.exception("camoufox: shutdown_all failed for %s", instance_id)

    async def reaper(self) -> None:
        """Kill instances idle beyond their TTL. Runs until cancelled."""
        try:
            while True:
                await asyncio.sleep(self._settings.reaper_interval_seconds)
                now = now_ts()
                for instance_id, inst in list(self._instances.items()):
                    if inst.status in {InstanceStatus.CLOSED, InstanceStatus.STOPPING}:
                        continue
                    if now - inst.last_active > inst.ttl_seconds:
                        logger.info("camoufox: reaping idle instance %s", instance_id)
                        try:
                            await self.kill(instance_id)
                        except Exception:
                            logger.exception(
                                "camoufox: reaper kill failed for %s", instance_id
                            )
        except asyncio.CancelledError:
            return


REGISTRY = InstanceRegistry(SETTINGS)
