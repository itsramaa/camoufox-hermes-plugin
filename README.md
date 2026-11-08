# Camoufox Plugin

Anti-detect browser automation for Hermes. Launches **Camoufox**
(Playwright-compatible Firefox with engine-level fingerprint spoofing) for
concurrent guest sessions and persistent named profiles, behind an
SSE screencast and a Hermes dashboard grid UI.

## Capabilities

- **Guest sessions** — ephemeral temp-dir profiles, fully concurrent
  (bounded by a semaphore, default 3), auto-purged on close.
- **Persistent profiles** — `persistent_context=True` under
  `profiles/<name>/`; one instance per profile (second request → `409`).
- **Proxy** — dict `{server,username,password,bypass}`, DataImpulse
  session-id helper, `geoip=True` when a proxy is set.
- **Live screencast** — SSE stream of JPEG frames
  (`event: frame`, `event: status`, `: heartbeat`). Grid runs at 1.5 fps,
  the zoom modal at 6 fps; frames are base64 JPEGs from Playwright
  `page.screenshot(type="jpeg", quality=...)` (no PIL).
- **Dashboard** — grid view, per-tile live frame, zoom modal, force-close
  button.
- **Background reaper** — a `ctx.spawn_task` loop that kills instances idle
  past their TTL (guest 15 min, persistent 60 min).

## Model tools

| Tool | Purpose |
|------|---------|
| `camoufox_navigate` | Launch + navigate, returns `instance_id` |
| `camoufox_action` | click/fill/type/hover/scroll/evaluate on an instance |
| `camoufox_extract` | title/url/html/text/screenshot |
| `camoufox_close` | Close an instance and release resources |

## Layout

```
plugin.yaml                 # deps declared for Hermes PM
__init__.py                 # register(ctx): tools + reaper + on_unload
core/                       # registry, instances, locks, proxy, screencaster
tools/                      # JSON schemas + async handlers
dashboard/manifest.json    # tab + entry + api
dashboard/plugin_api.py     # standalone top-level router (bridges core)
dashboard/dist/index.js     # IIFE React grid UI
profiles/                   # persistent profile storage (gitignored)
tests/                      # pytest + pytest-asyncio smoke tests
```

## Process model & single-registry bridge

The agent process loads `__init__.py` under the `hermes_plugins.camoufox`
namespace; the dashboard web server imports `dashboard/plugin_api.py` as a
*standalone* top-level module. Both reach the same `core` module object by
putting the plugin root on `sys.path` and importing `core.instance_registry`
(whose `REGISTRY` is the single in-process singleton).

`hermes dashboard` and `hermes serve` may be **different OS processes**
(dashboard = UI server; serve = headless backend). When they are separate,
each process has its own `REGISTRY`; the dashboard API still serves its own
registry and does not crash. In the common embedded case they share one
process and one registry.

## Configuration

Defaults live in `core/config.py`; operators override via
`plugins.entries.camoufox.settings.<key>`: `max_guest_concurrency`,
`guest_ttl_seconds`, `persistent_ttl_seconds`, `default_fps`,
`default_jpeg_quality`, `default_headless`, `launch_timeout_seconds`,
`reaper_interval_seconds`, `profile_root`.

## Headless / virtual

Windows host with a Linux-staged venv (Python 3.14.9): no Xvfb assumption.
`default_headless=True` keeps the grid safe. `headless` may be overridden to
`False`; `"virtual"` (Xvfb) is **Linux-only** and is rejected on Windows
(Camoufox raises `VirtualDisplayNotSupported`).

## Dependencies

`camoufox`, `playwright`, `psutil` are declared in `plugin.yaml`
`pip_dependencies`; Hermes PM installs them. **Not** installed by this
plugin, and a missing runtime raises `DependencyMissingError` (HTTP 503) at
launch, not at import.

## Validation status

- Byte-compiles + static import check (see `tests/`).
- Real browser launch (camoufox/playwright + `playwright install`) was NOT
  run — requires dependency install, out of scope for this build.
