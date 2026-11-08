"""Per-profile exclusivity via an on-disk marker.

Two processes sharing a persistent profile must not race: the atomic
``O_CREAT|O_EXCL`` marker is the cross-process guard. In-process serialization
is owned by the registry's per-profile asyncio locks.
"""

from __future__ import annotations

import os
from pathlib import Path

from .exceptions import ProfileLockedError

_LOCK_NAME = ".hermes_profile.lock"


class ProfileLockManager:
    def __init__(self, profiles_root: Path) -> None:
        self._profiles_root = Path(profiles_root)

    def acquire_disk(self, profile: str) -> Path:
        """Atomically claim the on-disk lock; raise ProfileLockedError if held."""
        directory = self._profiles_root / profile
        directory.mkdir(parents=True, exist_ok=True)
        marker = directory / _LOCK_NAME
        try:
            fd = os.open(str(marker), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            raise ProfileLockedError(
                f"profile {profile!r} is already in use by another process"
            ) from None
        with os.fdopen(fd, "w") as handle:
            handle.write(str(os.getpid()))
        return marker

    def release_disk(self, profile: str) -> None:
        marker = self._profiles_root / profile / _LOCK_NAME
        marker.unlink(missing_ok=True)

    def is_locked_on_disk(self, profile: str) -> bool:
        return (self._profiles_root / profile / _LOCK_NAME).exists()
