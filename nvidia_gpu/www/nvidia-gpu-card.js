/*
 * NVIDIA GPU Stats — carte Lovelace maison (GPU + CPU/RAM en une seule vue).
 *
 * Détecte automatiquement les capteurs de l'intégration "nvidia_gpu" via
 * leur attribut "nvidia_gpu_key", sans aucun id d'entité codé en dur.
 * Les capteurs sont groupés par appareil (device) :
 *   - un appareil "GPU" (RTX …)      -> jauges GPU
 *   - un appareil "système" (CPU/RAM) -> jauges CPU / RAM
 * Plusieurs GPU et plusieurs machines coexistent donc sans conflit.
 *
 * Config (facultatif) :
 *   - "title"   : titre affiché (défaut "Serveur — GPU & CPU")
 *   - "entities": liste d'entités à forcer (défaut : auto-détection)
 */
(() => {
  "use strict";
  if (customElements.get("nvidia-gpu-card")) return;

  // ---- metric definitions, keyed by nvidia_gpu_key -----------------------
  // "isGpu" marks metrics that belong to a GPU device; the same key name
  // (temperature_c / *_pct) exists on the system device with a different
  // meaning, so we classify the device first and only then read metrics.
  const GPU_METRICS = [
    { key: "gpu_utilization_pct", label: "Utilisation", min: 0, max: 100, unit: "%" },
    { key: "memory_used_pct",     label: "Mémoire",     min: 0, max: 100, unit: "%" },
    { key: "power_usage_pct",     label: "Puissance",   min: 0, max: 100, unit: "%" },
    { key: "fan_speed_pct",       label: "Ventilateur", min: 0, max: 100, unit: "%" },
    { key: "temperature_c",       label: "Temp. GPU",   min: 0, max: 90,  unit: "°C", warn: 70, danger: 85 },
    { key: "memory_used_gib",     label: "Mémoire",     min: 0, max: 48,  unit: "GiB" },
    { key: "power_draw_w",        label: "Consommation",min: 0, max: 300, unit: "W" },
  ];
  const SYS_METRICS = [
    { key: "usage_pct",      label: "CPU",      min: 0, max: 100, unit: "%" },
    { key: "ram_used_pct",   label: "RAM",      min: 0, max: 100, unit: "%" },
    { key: "temperature_c",  label: "Temp. CPU",min: 0, max: 100, unit: "°C", warn: 70, danger: 85 },
    { key: "ram_used_gib",   label: "RAM",      min: 0, max: 64,  unit: "GiB" },
  ];

  const style = new CSSStyleSheet();
  style.replaceSync(`
    :host { display: block; }
    .wrap { padding: 4px 2px; }
    .title { font-size: 1.1em; font-weight: 600; margin: 0 0 14px; color: var(--primary-text-color,#111); }
    .device { margin-bottom: 22px; }
    .device:last-child { margin-bottom: 2px; }
    .dtitle { font-size: .92em; font-weight: 600; color: var(--secondary-text-color,#555);
              margin: 0 0 10px; display: flex; align-items: center; gap: 8px; }
    .dot { width: 8px; height: 8px; border-radius: 50%; flex: 0 0 auto; }
    .dot.gpu { background: #76b900; }
    .dot.sys { background: #03a9f4; }
    .grid { display: flex; flex-wrap: wrap; gap: 10px; }
    .gauge { flex: 1 1 150px; min-width: 130px; max-width: 230px; text-align: center;
             background: var(--card-background-color,#fff); border-radius: 12px;
             padding: 10px 10px 12px; box-shadow: 0 1px 3px rgba(0,0,0,.08); }
    .gauge svg { width: 100%; height: auto; display: block; }
    .glabel { font-size: .78em; color: var(--secondary-text-color,#666); margin-top: 2px; }
    .empty { padding: 24px; text-align: center; color: var(--secondary-text-color,#888); font-size: .9em; }
  `);

  const SVGNS = "http://www.w3.org/2000/svg";

  class NvCard extends HTMLElement {
    constructor() {
      super();
      this._hass = null;
      this._config = { type: "custom:nvidia-gpu-card" };
      const root = this.attachShadow({ mode: "open" });
      root.adoptedStyleSheets = [style];
      this._root = document.createElement("div");
      this._root.className = "wrap";
      root.appendChild(this._root);
    }
    set hass(v) {
      this._hass = v;
      // Render once config is ready (Lovelace may set hass before or after
      // setConfig, so re-render on whichever arrives second).
      if (this._config) this._render();
    }
    get hass() { return this._hass; }
    // Lovelace card API — the frontend calls these methods (not the .config property).
    setConfig(cfg) {
      this._config = cfg || { type: "custom:nvidia-gpu-card" };
      if (this._hass) this._render();
    }
    getConfig() { return this._config; }
    getCardSize() { return 5; }
    // Keep the .config property in sync (harmless if the frontend uses it).
    set config(c) { this.setConfig(c); }
    get config() { return this._config; }
    static getStubConfig() { return { title: "Serveur — GPU & CPU" }; }

    _num(id) {
      const s = this._hass.states[id];
      const v = s && s.state === "unknown" ? NaN : parseFloat(s.state);
      return v;
    }
    _key(id) {
      const s = this._hass.states[id];
      return s && s.attributes ? s.attributes.nvidia_gpu_key : undefined;
    }
    _device(id) {
      const s = this._hass.states[id];
      return s && s.attributes ? s.attributes.device_id : undefined;
    }
    _friendly(id) {
      const s = this._hass.states[id];
      return s && s.attributes ? s.attributes.friendly_name : id;
    }

    // Group this integration's sensors by device.
    _groups() {
      const states = this._hass.states || {};
      let ids = (this._config && this._config.entities) || [];
      if (!ids.length) {
        ids = Object.keys(states).filter(
          (id) => id.startsWith("sensor.") && this._key(id) !== undefined
        );
      }
      const byDevice = new Map();
      for (const id of ids) {
        const k = this._key(id);
        if (k === undefined) continue;
        const dev = this._device(id) || "_gpu";
        if (!byDevice.has(dev)) byDevice.set(dev, {});
        byDevice.get(dev)[k] = id;
      }
      // Classify each group: GPU if it has a GPU-usage metric, else system.
      const out = [];
      for (const [dev, map] of byDevice.entries()) {
        const isGpu = "gpu_utilization_pct" in map;
        const title = this._friendly(Object.values(map)[0]) || (isGpu ? "GPU" : "CPU");
        out.push({ isGpu, title, map, metrics: isGpu ? GPU_METRICS : SYS_METRICS });
      }
      // GPU devices first, then system; stable by title.
      out.sort((a, b) => (a.isGpu === b.isGpu ? a.title.localeCompare(b.title) : (a.isGpu ? -1 : 1)));
      return out;
    }

    _gauge(spec, entityId) {
      const raw = this._num(entityId);
      const frac = isFinite(raw) ? Math.max(0, Math.min(1, (raw - spec.min) / (spec.max - spec.min))) : 0;
      const hasValue = isFinite(raw);
      // colour: severity if set, else neutral
      let color = "#76b900";
      if (hasValue) {
        if (spec.danger !== undefined && raw >= spec.danger) color = "#f44336";
        else if (spec.warn !== undefined && raw >= spec.warn) color = "#ff9800";
      }
      const el = document.createElement("div");
      el.className = "gauge";

      // semicircle geometry
      const W = 160, H = 96, cx = W / 2, cy = H - 14, r = 62, sw = 16;
      const path = document.createElementNS(SVGNS, "path");
      const arc = (from, to) => {
        const a0 = Math.PI * (1 - from), a1 = Math.PI * (1 - to);
        const x0 = cx - r * Math.cos(a0), y0 = cy - r * Math.sin(a0);
        const x1 = cx - r * Math.cos(a1), y1 = cy - r * Math.sin(a1);
        return `M ${x0} ${y0} A ${r} ${r} 0 0 1 ${x1} ${y1}`;
      };
      const track = document.createElementNS(SVGNS, "path");
      track.setAttribute("d", arc(0, 1));
      track.setAttribute("fill", "none");
      track.setAttribute("stroke", "rgba(0,0,0,.10)");
      track.setAttribute("stroke-width", sw);
      track.setAttribute("stroke-linecap", "round");
      const fill = document.createElementNS(SVGNS, "path");
      const d = frac > 0 ? arc(0, frac) : "M 1 1";
      fill.setAttribute("d", d);
      fill.setAttribute("fill", "none");
      fill.setAttribute("stroke", hasValue ? color : "rgba(0,0,0,.25)");
      fill.setAttribute("stroke-width", sw);
      fill.setAttribute("stroke-linecap", "round");

      const val = document.createElementNS(SVGNS, "text");
      val.setAttribute("x", cx); val.setAttribute("y", cy - 12);
      val.setAttribute("text-anchor", "middle");
      val.setAttribute("font-size", "26"); val.setAttribute("font-weight", "600");
      val.setAttribute("fill", hasValue ? "var(--primary-text-color,#111)" : "rgba(0,0,0,.35)");
      val.textContent = hasValue ? (Math.round(raw * 10) / 10) : "—";
      const unit = document.createElementNS(SVGNS, "text");
      unit.setAttribute("x", cx); unit.setAttribute("y", cy - 1);
      unit.setAttribute("text-anchor", "middle"); unit.setAttribute("font-size", "12");
      unit.setAttribute("fill", "var(--secondary-text-color,#777)");
      unit.textContent = spec.unit;

      const svg = document.createElementNS(SVGNS, "svg");
      svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
      svg.setAttribute("preserveAspectRatio", "xMidYMid meet");
      svg.append(track, fill, val, unit);
      el.appendChild(svg);
      const lab = document.createElement("div");
      lab.className = "glabel";
      lab.textContent = spec.label;
      el.appendChild(lab);
      return el;
    }

    _render() {
      const root = this._root;
      root.innerHTML = "";
      const title = this._config && this._config.title;
      if (title) {
        const t = document.createElement("div");
        t.className = "title"; t.textContent = title; root.appendChild(t);
      }
      const groups = this._groups();
      if (!groups.length) {
        const e = document.createElement("div");
        e.className = "empty";
        e.textContent = "Aucun capteur nvidia_gpu détecté.";
        root.appendChild(e);
        return;
      }
      for (const g of groups) {
        const dev = document.createElement("div");
        dev.className = "device";
        const dt = document.createElement("div");
        dt.className = "dtitle";
        const dot = document.createElement("span");
        dot.className = "dot " + (g.isGpu ? "gpu" : "sys");
        dt.appendChild(dot);
        const dtxt = document.createElement("span");
        dtxt.textContent = g.title;
        dt.appendChild(dtxt);
        dev.appendChild(dt);
        const grid = document.createElement("div");
        grid.className = "grid";
        for (const spec of g.metrics) {
          const id = g.map[spec.key];
          if (id) grid.appendChild(this._gauge(spec, id));
        }
        dev.appendChild(grid);
        root.appendChild(dev);
      }
    }
  }

  // ---- editor -----------------------------------------------------------
  class NvCardEditor extends HTMLElement {
    setConfig(cfg) { this._config = cfg || { type: "custom:nvidia-gpu-card" }; this._render(); }
    _render() {
      this.innerHTML = "";
      const wrap = document.createElement("div");
      wrap.style.padding = "8px 0";
      const label = document.createElement("label");
      label.style.display = "block"; label.style.marginBottom = "6px";
      label.textContent = "Titre (optionnel)";
      const input = document.createElement("input");
      input.type = "text"; input.value = this._config.title || "";
      input.style.width = "100%"; input.style.padding = "8px"; input.style.boxSizing = "border-box";
      input.onchange = () => {
        this._config = { ...this._config, title: input.value || undefined };
        this.dispatchEvent(new CustomEvent("config-changed", { detail: { config: this._config } }));
      };
      const help = document.createElement("div");
      help.style.marginTop = "10px"; help.style.fontSize = ".85em";
      help.style.color = "var(--secondary-text-color,#666)";
      help.innerHTML = "La carte détecte automatiquement les capteurs de l'intégration " +
        "<b>nvidia_gpu</b> (GPU + CPU/RAM) sur toutes vos machines. " +
        "Le titre est facultatif.";
      wrap.append(label, input, help);
      this.appendChild(wrap);
    }
  }

  customElements.define("nvidia-gpu-card", NvCard);
  customElements.define("nvidia-gpu-card-editor", NvCardEditor);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "nvidia-gpu-card",
    name: "NVIDIA GPU Stats",
    description: "Jauges GPU + CPU/RAM de l'intégration nvidia_gpu (multi-GPU / multi-serveur).",
    preview: true,
    documentationUrl: "https://github.com/thomasbidou/NVIDIA_GPU_Metric",
  });
})();
