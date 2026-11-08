/**
 * Camoufox Dashboard Plugin
 * Grid of live browser instances (SSE screencast), create/kill controls,
 * zoom modal, and declarative Scenarios manager.
 */
(function () {
  "use strict";

  const SDK = window.__HERMES_PLUGIN_SDK__;
  const { React } = SDK;
  const { Card, CardHeader, CardTitle, CardContent, Badge, Button, Input, Select, Separator } = SDK.components;
  const { useState, useEffect, useCallback, useMemo, useRef } = SDK.hooks;
  const { cn, timeAgo } = SDK.utils;

  const GRID_FPS = 1.5;
  const ZOOM_FPS = 6.0;
  const QUALITY = 50;

  function fetchAPI(path, opts) {
    opts = opts || {};
    var headers = Object.assign({}, opts.headers);
    if (opts.body && typeof opts.body === "string" && !headers["Content-Type"]) {
      headers["Content-Type"] = "application/json";
    }
    opts.headers = headers;
    return SDK.fetchJSON(path, opts).catch(function (e) {
      return { __error: e ? e.message : "request failed" };
    });
  }

  // ── Live frame tile: subscribes to SSE and renders the latest JPEG. ──
  function FrameTile({ instanceId, fps, onZoom, onKill, showControls }) {
    const imgRef = useRef(null);
    const [status, setStatus] = useState("starting");
    const [url, setUrl] = useState(null);
    const [title, setTitle] = useState(null);

    useEffect(function () {
      const es = new EventSource(
        "/api/plugins/camoufox/instances/" + instanceId +
        "/stream?fps=" + fps + "&quality=" + QUALITY
      );
      const onFrame = function (ev) {
        try {
          const data = JSON.parse(ev.data);
          if (imgRef.current) { imgRef.current.src = data.image; }
          setUrl(data.url || null);
          setTitle(data.title || null);
          setStatus(data.status || "starting");
        } catch (e) { /* ignore */ }
      };
      const onStatus = function (ev) {
        try {
          const data = JSON.parse(ev.data);
          setStatus(data.status || "closed");
        } catch (e) { /* ignore */ }
      };
      es.addEventListener("frame", onFrame);
      es.addEventListener("status", onStatus);
      es.onerror = function () { /* auto-reconnect */ };
      return function () { es.close(); };
    }, [instanceId, fps]);

    return React.createElement("div", { className: "relative h-full w-full overflow-hidden" },
      React.createElement("img", {
        ref: imgRef,
        alt: instanceId,
        className: "h-full w-full object-cover cursor-pointer",
        onClick: onZoom,
      }),
      React.createElement("div", { className: "absolute inset-x-0 bottom-0 flex items-center gap-2 bg-black/60 px-2 py-1 text-[10px] font-courier text-white" },
        React.createElement(Badge, { variant: "outline" }, status),
        React.createElement("span", { className: "truncate flex-1", title: url || title },
          url || title || instanceId),
        showControls ? React.createElement("div", { className: "flex gap-1" },
          React.createElement(Button, {
            className: "h-5 px-1 text-[10px]", onClick: onZoom,
          }, "Zoom"),
          React.createElement(Button, {
            "data-variant": "destructive",
            className: "h-5 px-1 text-[10px] text-red-400", onClick: onKill,
          }, "Kill"),
        ) : null,
      ),
    );
  }

  function ZoomModal({ instance, onClose, onKill }) {
    useEffect(function () {
      const onKey = function (e) { if (e.key === "Escape") onClose(); };
      document.addEventListener("keydown", onKey);
      return function () { document.removeEventListener("keydown", onKey); };
    }, [onClose]);
    return React.createElement("div", {
      className: "fixed inset-0 z-50 flex items-center justify-center bg-black/80",
    },
      React.createElement("div", { className: "w-[min(1200px,95vw)]" },
        React.createElement("div", { className: "flex items-center justify-between border-b border-border px-3 py-2" },
          React.createElement("span", { className: "text-sm font-courier text-white" }, instance.id),
          React.createElement(Button, { onClick: onClose, className: "text-sm" }, "Close (Esc)"),
        ),
        React.createElement("div", { className: "aspect-video w-full bg-black" },
          React.createElement(FrameTile, {
            instanceId: instance.id,
            fps: ZOOM_FPS,
            showControls: true,
            onKill: function () { onKill(instance.id); onClose(); },
            onZoom: onClose,
          }),
        ),
      ),
    );
  }

  // ── Scenarios View Component ──
  function ScenariosSection() {
    const [scenarios, setScenarios] = useState([]);
    const [runningId, setRunningId] = useState(null);
    const [runResult, setRunResult] = useState(null);
    const [runError, setRunError] = useState(null);

    function loadScenarios() {
      fetchAPI("/api/plugins/camoufox/scenarios").then(function (res) {
        if (!res.__error && res.scenarios) {
          setScenarios(res.scenarios);
        }
      });
    }

    useEffect(function () {
      loadScenarios();
    }, []);

    function runScenario(id) {
      setRunningId(id);
      setRunResult(null);
      setRunError(null);
      fetchAPI("/api/plugins/camoufox/scenarios/" + id + "/run", {
        method: "POST",
        body: JSON.stringify({ mode: "guest", headless: true }),
      }).then(function (res) {
        if (res.__error || res.detail) {
          setRunError(res.__error || res.detail);
        } else if (res.run) {
          setRunResult(res.run);
        }
      }).catch(function (err) {
        setRunError(String(err));
      }).finally(function () {
        setRunningId(null);
      });
    }

    function resumeRun(runId) {
      fetchAPI("/api/plugins/camoufox/scenarios/runs/" + runId + "/resume", { method: "POST" })
        .then(function () {
          setRunResult(function (prev) {
            return prev ? { ...prev, status: "resumed" } : prev;
          });
        });
    }

    return React.createElement("div", { className: "flex flex-col gap-4" },
      React.createElement(Card, null,
        React.createElement(CardHeader, null,
          React.createElement("div", { className: "flex items-center justify-between" },
            React.createElement("div", { className: "flex items-center gap-2" },
              React.createElement(CardTitle, { className: "text-lg" }, "Declarative Scenarios"),
              React.createElement(Badge, { variant: "outline" }, scenarios.length + " saved"),
            ),
            React.createElement(Button, { onClick: loadScenarios, className: "text-xs h-7" }, "Refresh"),
          ),
        ),
        React.createElement(CardContent, { className: "flex flex-col gap-3" },
          scenarios.length === 0
            ? React.createElement("div", { className: "py-6 text-center text-sm text-muted-foreground" },
                "No saved scenarios yet. Add YAML scenarios to data/plugins/camoufox/scenarios/.")
            : React.createElement("div", { className: "flex flex-col gap-2" },
                scenarios.map(function (scn) {
                  const isThisRunning = runningId === scn.id;
                  return React.createElement("div", {
                    key: scn.id,
                    className: "flex items-center justify-between p-3 border border-border rounded bg-muted/20 hover:bg-muted/30",
                  },
                    React.createElement("div", { className: "flex flex-col gap-1" },
                      React.createElement("div", { className: "flex items-center gap-2" },
                        React.createElement("span", { className: "font-semibold text-sm" }, scn.name || scn.id),
                        React.createElement(Badge, { variant: "secondary", className: "text-[10px]" }, scn.id),
                        React.createElement(Badge, { variant: "outline", className: "text-[10px]" }, scn.steps_count + " steps"),
                      ),
                      scn.description ? React.createElement("span", { className: "text-xs text-muted-foreground" }, scn.description) : null,
                    ),
                    React.createElement(Button, {
                      disabled: runningId !== null,
                      onClick: function () { runScenario(scn.id); },
                      className: "text-xs h-8 px-3",
                    }, isThisRunning ? "Running..." : "▶ Run"),
                  );
                }),
              ),
        ),
      ),

      (runResult || runError) ? React.createElement(Card, null,
        React.createElement(CardHeader, null,
          React.createElement("div", { className: "flex items-center justify-between" },
            React.createElement(CardTitle, { className: "text-base" }, "Scenario Execution Outcome"),
            runResult ? React.createElement(Badge, {
              className: runResult.status === "completed" ? "bg-green-600 text-white" : "bg-red-600 text-white",
            }, runResult.status) : null,
          ),
        ),
        React.createElement(CardContent, { className: "flex flex-col gap-2 text-xs font-courier" },
          runError ? React.createElement("div", { className: "p-2 bg-red-950/40 text-red-300 border border-red-800 rounded" },
            runError) : null,
          runResult ? React.createElement("div", { className: "flex flex-col gap-2" },
            runResult.status === "paused" ? React.createElement("div", { className: "flex items-center justify-between p-2 bg-amber-950/40 border border-amber-800 rounded" },
              React.createElement("span", { className: "text-amber-300" }, runResult.pause_prompt || "Paused for interaction"),
              React.createElement(Button, { onClick: function () { resumeRun(runResult.run_id); }, className: "h-6 text-xs px-2" }, "Resume"),
            ) : null,
            React.createElement("div", { className: "font-semibold text-foreground pt-1" }, "Output Variables:"),
            React.createElement("pre", { className: "p-2 bg-muted/40 rounded overflow-auto text-[11px]" },
              JSON.stringify(runResult.vars, null, 2)),
            runResult.logs && runResult.logs.length > 0 ? React.createElement("div", { className: "font-semibold text-foreground pt-1" }, "Step Logs:") : null,
            runResult.logs && runResult.logs.length > 0 ? React.createElement("div", { className: "flex flex-col gap-1 max-h-60 overflow-auto" },
              runResult.logs.map(function (log, idx) {
                return React.createElement("div", { key: idx, className: "flex items-center justify-between p-1 bg-muted/20 border border-border/50 text-[10px]" },
                  React.createElement("span", null, log.step_name + " (" + log.action + ")"),
                  React.createElement(Badge, { variant: log.status === "success" ? "outline" : "destructive", className: "text-[9px]" }, log.status),
                );
              }),
            ) : null,
          ) : null,
        ),
      ) : null,
    );
  }

  function CamoufoxPage() {
    const [activeTab, setActiveTab] = useState("browsers");
    const [instances, setInstances] = useState([]);
    const [stats, setStats] = useState(null);
    const [busy, setBusy] = useState(false);
    const [form, setForm] = useState({ mode: "guest", profile: "", url: "", proxyServer: "", proxyUser: "", proxyPass: "" });
    const [zoomId, setZoomId] = useState(null);
    const timerRef = useRef(null);

    function refresh() {
      return fetchAPI("/api/plugins/camoufox/instances").then(function (data) {
        if (data.__error) { setInstances([]); setStats(null); return; }
        setInstances(data.instances || []);
        setStats(data.stats || null);
      });
    }

    useEffect(function () {
      refresh();
      timerRef.current = setInterval(refresh, 5000);
      return function () { if (timerRef.current) clearInterval(timerRef.current); };
    }, []);

    function kill(id) {
      fetchAPI("/api/plugins/camoufox/instances/" + id + "/kill", { method: "POST" })
        .then(refresh).catch(function () {});
    }

    function create() {
      setBusy(true);
      const proxy = form.proxyServer ? { server: form.proxyServer } : null;
      if (proxy && form.proxyUser) proxy.username = form.proxyUser;
      if (proxy && form.proxyPass) proxy.password = form.proxyPass;
      const body = { mode: form.mode, url: form.url || null };
      if (form.mode === "persistent") body.profile = form.profile || "default";
      if (proxy) body.proxy = proxy;
      fetchAPI("/api/plugins/camoufox/instances", { method: "POST", body: JSON.stringify(body) })
        .then(function () { setForm(function (f) { return { ...f, url: "" }; }); return refresh(); })
        .catch(function () {})
        .finally(function () { setBusy(false); });
    }

    const zoomInstance = useMemo(function () {
      return instances.find(function (i) { return i.id === zoomId; }) || null;
    }, [zoomId, instances]);

    return React.createElement("div", { className: "flex flex-col gap-4" },
      React.createElement("div", { className: "flex items-center gap-2 border-b border-border pb-2" },
        React.createElement(Button, {
          variant: activeTab === "browsers" ? "default" : "outline",
          className: "text-xs h-8 px-4",
          onClick: function () { setActiveTab("browsers"); },
        }, "Live Browsers " + (stats ? "(" + stats.running + ")" : "")),
        React.createElement(Button, {
          variant: activeTab === "scenarios" ? "default" : "outline",
          className: "text-xs h-8 px-4",
          onClick: function () { setActiveTab("scenarios"); },
        }, "Scenarios (Engine)"),
      ),

      activeTab === "scenarios" ? React.createElement(ScenariosSection, null) : React.createElement(React.Fragment, null,
        React.createElement(Card, null,
          React.createElement(CardHeader, null,
            React.createElement("div", { className: "flex items-center gap-3" },
              React.createElement(CardTitle, { className: "text-lg" }, "Camoufox Browsers"),
              stats ? React.createElement(Badge, { variant: "outline" }, stats.running + " running") : null,
            ),
          ),
          React.createElement(CardContent, { className: "flex flex-col gap-3" },
            React.createElement("div", { className: "grid grid-cols-1 gap-2 sm:grid-cols-2" },
              React.createElement(Input, { placeholder: "URL", value: form.url, onChange: function (e) { setForm({ ...form, url: e.target.value }); } }),
              React.createElement(Select, {
                value: form.mode,
                onChange: function (e) { setForm({ ...form, mode: e.target.value }); },
                className: "bg-background",
              },
                [
                  React.createElement("option", { key: "guest", value: "guest" }, "guest"),
                  React.createElement("option", { key: "persistent", value: "persistent" }, "persistent"),
                ],
              ),
              form.mode === "persistent" ? React.createElement(Input, {
                placeholder: "profile name",
                value: form.profile,
                onChange: function (e) { setForm({ ...form, profile: e.target.value }); },
              }) : null,
            ),
            React.createElement("div", { className: "grid grid-cols-3 gap-2" },
              React.createElement(Input, { placeholder: "proxy server", value: form.proxyServer, onChange: function (e) { setForm({ ...form, proxyServer: e.target.value }); } }),
              React.createElement(Input, { placeholder: "proxy user", value: form.proxyUser, onChange: function (e) { setForm({ ...form, proxyUser: e.target.value }); } }),
              React.createElement(Input, { placeholder: "proxy pass", value: form.proxyPass, onChange: function (e) { setForm({ ...form, proxyPass: e.target.value }); } }),
            ),
            React.createElement(Button, { onClick: create, disabled: busy, className: "w-full" },
              busy ? "Launching..." : "+ Launch instance"),
          ),
        ),

        instances.length === 0
          ? React.createElement("div", { className: "py-10 text-center text-sm text-muted-foreground" },
              "No running instances. Launch one above.")
          : React.createElement("div", { className: "grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3" },
              instances.map(function (inst) {
                return React.createElement("div", { key: inst.id, className: "border border-border" },
                  React.createElement("div", { className: "flex items-center justify-between px-2 py-1" },
                    React.createElement("span", { className: "font-courier text-xs text-muted-foreground" },
                      (inst.profile ? inst.profile + "/" : "") + inst.id + " · " + inst.mode),
                    React.createElement(Button, {
                      "data-variant": "destructive",
                      className: "h-5 px-1 text-[10px] text-red-400",
                      onClick: function (e) { e.stopPropagation(); kill(inst.id); },
                    }, "Force close"),
                  ),
                  React.createElement("div", { className: "aspect-video w-full bg-black cursor-pointer",
                      onClick: function () { setZoomId(inst.id); },
                    },
                    React.createElement(FrameTile, {
                      instanceId: inst.id,
                      fps: GRID_FPS,
                      showControls: false,
                      onKill: function (e) { if (e && e.stopPropagation) e.stopPropagation(); kill(inst.id); },
                      onZoom: function () { setZoomId(inst.id); },
                    }),
                  ),
                );
              }),
            ),

        zoomInstance ? React.createElement(ZoomModal, {
          instance: zoomInstance,
          onKill: kill,
          onClose: function () { setZoomId(null); },
        }) : null,
      ),
    );
  }

  window.__HERMES_PLUGINS__.register("camoufox", CamoufoxPage);
})();
