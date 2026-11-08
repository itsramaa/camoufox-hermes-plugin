"""Exception hierarchy for the camoufox plugin."""

from __future__ import annotations


class CamoufoxPluginError(Exception):
    """Base class for plugin errors with an HTTP-mapping status code."""

    status_code = 500

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        if status_code is not None:
            self.status_code = status_code


class ProfileLockedError(CamoufoxPluginError):
    """A persistent profile is already in use."""

    status_code = 409


class InstanceNotFoundError(CamoufoxPluginError):
    """The requested browser instance does not exist."""

    status_code = 404


class MaxConcurrencyReachedError(CamoufoxPluginError):
    """Guest concurrency limit reached."""

    status_code = 429


class DependencyMissingError(CamoufoxPluginError):
    """camoufox/playwright (or their runtime) is not installed."""

    status_code = 503


class SystemDependencyMissingError(DependencyMissingError):
    """OS-level system libraries for Firefox/Camoufox (e.g. libgtk-3) are missing."""

    status_code = 503

