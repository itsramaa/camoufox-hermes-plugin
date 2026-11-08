/**
 * Camoufox Dashboard Plugin
 * Grid of live browser instances (SSE screencast), create/kill controls,
 * zoom modal at high FPS. Plain IIFE using the Hermes Plugin SDK globals.
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
        } catch (e) { /* ignore malformed frame */ }
      };
      const onStatus = function (ev) {
        try {
          const data = JSON.parse(ev.data);
          setStatus(data.status || "closed");
        } catch (e) { /* ignore */ }
      };
      es.addEventListener("frame", onFrame);
      es.addEventListener("status", onStatus);
      es.onerror = function () { /* EventSource auto-reconnects; keep tiles stable */ };
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

  function ZoomModal({ instance, onClose }) {
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
          React.createElement("span", { className: "text-sm font-courier" }, instance.id),
          React.createElement(Button, { onClick: onClose, className: "text-sm" }, "Close (Esc)"),
        ),
        React.createElement("div", { className: "aspect-video w-full bg-black" },
          React.createElement(FrameTile, {
            instanceId: instance.id,
            fps: ZOOM_FPS,
            showControls: true,
            onKill: function () { kill(instance.id); onClose(); },
            onZoom: onClose,
          }),
        ),
      ),
    );
  }

  function CamoufoxPage() {
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
        onClose: function () { setZoomId(null); },
      }) : null,
    );
  }

  window.__HERMES_PLUGINS__.register("camoufox", CamoufoxPage);
})();
