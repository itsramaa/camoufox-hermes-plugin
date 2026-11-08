"""Camoufox dashboard backend API.

Mounted at /api/plugins/camoufox/ by the Hermes dashboard plugin system.
This file is imported as a *standalone* top-level module (not as part of the
hermes_plugins package), so it bridges ``core`` onto ``sys.path`` and reuses the
same module object the agent-side plugin registers.
"""

from __future__ import annotations

import importlib
import sys
import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, model_validator

router = APIRouter()

import logging

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


# Bridge: make the plugin root importable so ``core.*`` resolves to the same
# module object whether imported by the package entry point or this standalone
# dashboard module.
_PLUGIN_ROOT = Path(__file__).resolve().parent.parent
if str(_PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_ROOT))

# Import (or reuse) the shared core modules.
try:
    _reg_mod = importlib.import_module("core.instance_registry")
    _scr_mod = importlib.import_module("core.screencaster")
    _exc_mod = importlib.import_module("core.exceptions")
    _mdl_mod = importlib.import_module("core.models")
    _scn_store = importlib.import_module("core.scenario_storage")
    _scn_eng = importlib.import_module("core.scenario_engine")
except Exception:
    # Fallback: load by path under unique names (best effort).
    _reg_mod = None
    _scr_mod = None
    _exc_mod = None
    _mdl_mod = None
    _scn_store = None
    _scn_eng = None


def _get(name: str, mod: Any, alt: str):
    if mod is not None and hasattr(mod, name):
        return getattr(mod, name)
    raise HTTPException(status_code=503, detail=f"camoufox core unavailable ({alt})")


def REGISTRY():
    return _get("REGISTRY", _reg_mod, "registry")


def sse_stream(*args: Any, **kwargs: Any):
    return _get("sse_stream", _scr_mod, "screencaster")(*args, **kwargs)


def SCENARIO_STORAGE():
    return _get("STORAGE", _scn_store, "scenario_storage")


def SCENARIO_ENGINE():
    return _get("ENGINE", _scn_eng, "scenario_engine")


def _error_to_http(exc: Exception) -> HTTPException:
    status = getattr(exc, "status_code", 500)
    return HTTPException(status_code=status, detail=str(exc))


class ProxyBody(BaseModel):
    server: str
    username: str | None = None
    password: str | None = None
    bypass: str | None = None
    country: str | None = None
    session_id: str | None = None


class CreateInstanceBody(BaseModel):
    mode: str = Field(default="guest", pattern="^(guest|persistent)$")
    profile: str | None = None
    url: str | None = None
    proxy: ProxyBody | None = None
    headless: bool | None = None
    ttl_seconds: int | None = None

    @model_validator(mode="before")
    @classmethod
    def _parse_raw_json(cls, data: Any) -> Any:
        if isinstance(data, str):
            try:
                return json.loads(data)
            except Exception:
                return data
        return data


class GotoBody(BaseModel):
    url: str

    @model_validator(mode="before")
    @classmethod
    def _parse_raw_json(cls, data: Any) -> Any:
        if isinstance(data, str):
            try:
                return json.loads(data)
            except Exception:
                return data
        return data


@router.get("/instances")
async def list_instances() -> dict[str, Any]:
    try:
        reg = REGISTRY()
        return {"instances": reg.list(), "stats": reg.stats()}
    except HTTPException:
        raise
    except Exception as exc:
        raise _error_to_http(exc)


@router.post("/instances")
async def create_instance(body: CreateInstanceBody) -> dict[str, Any]:
    try:
        reg = REGISTRY()
        proxy = None
        if body.proxy and body.proxy.server:
            ProxySpec = _get("ProxySpec", _mdl_mod, "models")
            proxy = ProxySpec(
                server=body.proxy.server,
                username=body.proxy.username,
                password=body.proxy.password,
                bypass=body.proxy.bypass,
                country=body.proxy.country,
                session_id=body.proxy.session_id,
            )
            logger.debug(
                "camoufox: create_instance body mode=%s profile=%s url=%s proxy=%s",
                body.mode,
                body.profile,
                body.url,
                {
                    "server": body.proxy.server,
                    "username": _mask_username(body.proxy.username),
                    "password": _mask_password(body.proxy.password),
                },
            )
        inst = await reg.launch(
            mode=body.mode,
            profile=body.profile,
            start_url=body.url,
            proxy=proxy,
            headless=body.headless,
            ttl_seconds=body.ttl_seconds,
        )
        snap = await inst.snapshot()
        return snap.to_dict()
    except HTTPException:
        raise
    except Exception as exc:
        raise _error_to_http(exc)


@router.post("/instances/{instance_id}/kill")
async def kill_instance(instance_id: str) -> dict[str, Any]:
    try:
        ok = await REGISTRY().kill(instance_id)
        if not ok:
            raise HTTPException(
                status_code=404, detail=f"instance {instance_id!r} not found"
            )
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as exc:
        raise _error_to_http(exc)


@router.post("/instances/{instance_id}/goto")
async def goto_instance(instance_id: str, body: GotoBody) -> dict[str, Any]:
    try:
        inst = REGISTRY().get(instance_id)
        if inst is None:
            raise HTTPException(
                status_code=404, detail=f"instance {instance_id!r} not found"
            )
        await inst.goto(body.url)
        snap = await inst.snapshot()
        return snap.to_dict()
    except HTTPException:
        raise
    except Exception as exc:
        raise _error_to_http(exc)


@router.get("/instances/{instance_id}/stream")
async def stream_instance(
    instance_id: str,
    fps: float = Query(default=1.5, ge=0.5, le=10.0),
    quality: int = Query(default=50, ge=10, le=95),
) -> StreamingResponse:
    headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    return StreamingResponse(
        sse_stream(instance_id, fps=fps, quality=quality),
        media_type="text/event-stream",
        headers=headers,
    )


# -----------------------------------------------------------------------------
# Scenario Endpoints
# -----------------------------------------------------------------------------

class RunScenarioBody(BaseModel):
    variables: dict[str, Any] | None = None
    instance_id: str | None = None
    mode: str = Field(default="guest", pattern="^(guest|persistent)$")
    profile: str | None = None
    headless: bool | None = None


class SaveScenarioBody(BaseModel):
    scenario: dict[str, Any]


@router.get("/scenarios")
async def list_scenarios() -> dict[str, Any]:
    try:
        storage = SCENARIO_STORAGE()
        storage.seed_defaults_if_empty()
        return {"scenarios": storage.list()}
    except HTTPException:
        raise
    except Exception as exc:
        raise _error_to_http(exc)


@router.get("/scenarios/{scenario_id}")
async def get_scenario(scenario_id: str) -> dict[str, Any]:
    try:
        storage = SCENARIO_STORAGE()
        scenario = storage.get(scenario_id)
        return {"scenario": scenario.model_dump(by_alias=True)}
    except HTTPException:
        raise
    except Exception as exc:
        raise _error_to_http(exc)


@router.post("/scenarios")
async def save_scenario(body: SaveScenarioBody) -> dict[str, Any]:
    try:
        storage = SCENARIO_STORAGE()
        scenario = storage.save(body.scenario)
        return {"ok": True, "scenario": scenario.model_dump(by_alias=True)}
    except HTTPException:
        raise
    except Exception as exc:
        raise _error_to_http(exc)


@router.delete("/scenarios/{scenario_id}")
async def delete_scenario(scenario_id: str) -> dict[str, Any]:
    try:
        storage = SCENARIO_STORAGE()
        deleted = storage.delete(scenario_id)
        if not deleted:
            raise HTTPException(status_code=404, detail=f"Scenario {scenario_id!r} not found.")
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as exc:
        raise _error_to_http(exc)


@router.post("/scenarios/{scenario_id}/run")
async def run_scenario(scenario_id: str, body: RunScenarioBody) -> dict[str, Any]:
    try:
        storage = SCENARIO_STORAGE()
        engine = SCENARIO_ENGINE()
        scenario = storage.get(scenario_id)

        snapshot = await engine.execute(
            scenario,
            initial_vars=body.variables,
            instance_id=body.instance_id,
            mode=body.mode,
            profile=body.profile,
            headless=body.headless,
        )
        return {"run": snapshot.to_dict()}
    except HTTPException:
        raise
    except Exception as exc:
        raise _error_to_http(exc)


@router.post("/scenarios/runs/{run_id}/resume")
async def resume_scenario_run(run_id: str) -> dict[str, Any]:
    try:
        engine = SCENARIO_ENGINE()
        ok = await engine.resume_run(run_id)
        if not ok:
            raise HTTPException(status_code=404, detail=f"Run {run_id!r} not found or not in paused state.")
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as exc:
        raise _error_to_http(exc)


@router.post("/scenarios/runs/{run_id}/abort")
async def abort_scenario_run(run_id: str) -> dict[str, Any]:
    try:
        engine = SCENARIO_ENGINE()
        ok = await engine.abort_run(run_id)
        if not ok:
            raise HTTPException(status_code=404, detail=f"Run {run_id!r} not found.")
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as exc:
        raise _error_to_http(exc)

