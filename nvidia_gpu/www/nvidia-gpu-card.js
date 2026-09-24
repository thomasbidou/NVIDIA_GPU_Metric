/*
 * NVIDIA GPU Stats — carte Lovelace maison (GPU + CPU/RAM).
 *
 * Détecte automatiquement les capteurs de l'intégration "nvidia_gpu" via
 * leur attribut "nvidia_gpu_key", sans aucun id d'entité codé en dur.
 * Les capteurs sont groupés par appareil (device) :
 *   - un appareil "GPU" (RTX …)      -> métriques GPU
 *   - un appareil "système" (CPU/RAM) -> métriques CPU / RAM
 * Plusieurs GPU et plusieurs machines coexistent donc sans conflit.
 *
 * Rendu : cartes « stat » empilées, chacune = icône + libellé + valeur +
 * barre de progression (pill) colorée, style panneau admin sobre.
 *
 * Config (facultatif) :
 *   - "title"    : titre affiché (défaut vide)
 *   - "section"  : "all" (défaut) | "gpu" | "cpu" — ne montrer qu'une section
 *   - "entities" : liste d'entités à forcer (défaut : auto-détection)
 */
(() => {
  "use strict";
  if (customElements.get("nvidia-gpu-card")) return;

  // ---- palette ----------------------------------------------------------
  const C_BLUE   = "#3b82f6";
  const C_GREEN  = "#22c55e";
  const C_YELLOW = "#eab308";
  const C_RED    = "#ef4444";
  const ACCENT   = "#4a7ba6";   // fallback when a metric has no bands / no value

  // Color scales (bands: [threshold, color], ascending — the last band whose
  // threshold is <= the value wins). Temperature uses the requested scale:
  // 0–25 blue, 25–50 green, 50–70 yellow, 70+ red. Percentages mirror it.
  // Absolute metrics (GiB / W) use the same shape scaled to their max
  // (≈40 / 65 / 85 % of full).
  const PCT_BANDS  = [[0, C_BLUE], [25, C_GREEN], [50, C_YELLOW], [70, C_RED]];
  const TEMP_BANDS = [[0, C_BLUE], [25, C_GREEN], [50, C_YELLOW], [70, C_RED]];
  const GIB48_BANDS = [[0, C_BLUE], [19, C_GREEN], [31, C_YELLOW], [41, C_RED]];
  const GIB64_BANDS = [[0, C_BLUE], [26, C_GREEN], [42, C_YELLOW], [54, C_RED]];
  const W300_BANDS  = [[0, C_BLUE], [120, C_GREEN], [195, C_YELLOW], [255, C_RED]];
  const DOT_GPU = "#4a7ba6";
  const DOT_SYS = "#0ea5b7";

  // ---- inline icons (24x24, stroked) ------------------------------------
  const ICONS = {
    activity: "M3 12h4l3 8 4-16 3 8h4",
    memory:   "M7 7h10v10H7z M9 7V4M12 7V4M15 7V4 M9 20v-3M12 20v-3M15 20v-3 M7 9H4M7 12H4M7 15H4 M20 9h-3M20 12h-3M20 15h-3",
    thermo:   "M12 4a2 2 0 0 0-2 2v8.5a4 4 0 1 0 4 0V6a2 2 0 0 0-2-2z",
    bolt:     "M13 2L4 14h6l-1 8 9-12h-6l1-8z",
    fan:      "M12 9.5C12 5 15 3 17.5 4 17 7.5 15 9.5 12 9.5z M12 14.5C12 19 9 21 6.5 20 7 16.5 9 14.5 12 14.5z M9.5 12C5 12 3 9 4 6.5 7.5 7 9.5 9 9.5 12z M14.5 12C19 12 21 15 20 17.5 16.5 17 14.5 15 14.5 12z",
  };

  // ---- metric definitions, keyed by nvidia_gpu_key ----------------------
  const GPU_METRICS = [
    { key: "gpu_utilization_pct", label: "Utilisation",    min: 0, max: 100, unit: "%",   icon: ICONS.activity, bands: PCT_BANDS },
    { key: "memory_used_pct",     label: "Mémoire",        min: 0, max: 100, unit: "%",   icon: ICONS.memory,   bands: PCT_BANDS },
    { key: "temperature_c",       label: "Température",    min: 0, max: 90,  unit: "°C",  icon: ICONS.thermo,   bands: TEMP_BANDS },
    { key: "power_usage_pct",     label: "Puissance",      min: 0, max: 100, unit: "%",   icon: ICONS.bolt,     bands: PCT_BANDS },
    { key: "fan_speed_pct",       label: "Ventilateur",    min: 0, max: 100, unit: "%",   icon: ICONS.fan,      bands: PCT_BANDS },
    { key: "memory_used_gib",     label: "Mémoire (GiB)",  min: 0, max: 48,  unit: "GiB", icon: ICONS.memory,   bands: GIB48_BANDS },
    { key: "power_draw_w",        label: "Consommation",   min: 0, max: 300, unit: "W",   icon: ICONS.bolt,     bands: W300_BANDS },
  ];
  const SYS_METRICS = [
    { key: "usage_pct",      label: "CPU",        min: 0, max: 100, unit: "%",   icon: ICONS.activity, bands: PCT_BANDS },
    { key: "temperature_c",  label: "Température",min: 0, max: 100, unit: "°C",  icon: ICONS.thermo,   bands: TEMP_BANDS },
    { key: "ram_used_pct",   label: "RAM",        min: 0, max: 100, unit: "%",   icon: ICONS.memory,   bands: PCT_BANDS },
    { key: "ram_used_gib",   label: "RAM (GiB)",  min: 0, max: 64,  unit: "GiB", icon: ICONS.memory,   bands: GIB64_BANDS },
  ];

  const style = new CSSStyleSheet();
  style.replaceSync(`
    :host { display: block; }
    .wrap { padding: 4px 2px; }
    .title { font-size: 1.1em; font-weight: 600; margin: 0 0 14px;
             color: var(--primary-text-color,#1f2937); }
    .device { margin-bottom: 22px; }
    .device:last-child { margin-bottom: 2px; }
    .dtitle { font-size: .9em; font-weight: 600;
              color: var(--secondary-text-color,#475569);
              margin: 0 0 10px; display: flex; align-items: center; gap: 8px; }
    .dot { width: 8px; height: 8px; border-radius: 50%; flex: 0 0 auto; }
    .grid { display: flex; flex-direction: column; gap: 12px; }

    .card { background: var(--card-background-color,#fff);
            border: 1px solid var(--divider-color,#e5e7eb);
            border-radius: 10px; padding: 14px 16px 16px; }
    .head { display: flex; align-items: center; gap: 10px; }
    .icon { width: 20px; height: 20px; flex: 0 0 auto; }
    .icon svg { width: 100%; height: 100%; display: block; }
    .tlabel { font-weight: 600; color: var(--primary-text-color,#1f2937); font-size: .95em; }
    .value { color: var(--secondary-text-color,#6b7280); font-size: .9em;
             margin: 3px 0 12px 30px; }
    .track { height: 14px; border-radius: 999px; overflow: hidden;
             background: rgba(74,123,166,.16); }
    .fill { height: 100%; border-radius: 999px; transition: width .45s ease; }

    .empty { padding: 24px; text-align: center;
             color: var(--secondary-text-color,#888); font-size: .9em; }
  `);

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
      if (this._config) this._render();
    }
    get hass() { return this._hass; }
    setConfig(cfg) {
      this._config = cfg || { type: "custom:nvidia-gpu-card" };
      if (this._hass) this._render();
    }
    getConfig() { return this._config; }
    getCardSize() { return 16; }
    set config(c) { this.setConfig(c); }
    get config() { return this._config; }
    static getStubConfig() { return { title: "Serveur — GPU & CPU" }; }

    _num(id) {
      const s = this._hass && this._hass.states[id];
      const v = s && s.state === "unknown" ? NaN : parseFloat(s.state);
      return v;
    }
    _key(id) {
      const s = this._hass && this._hass.states[id];
      return s && s.attributes ? s.attributes.nvidia_gpu_key : undefined;
    }
    _section(id) {
      const s = this._hass && this._hass.states[id];
      return s && s.attributes ? s.attributes.nvidia_gpu_section : undefined;
    }
    _device(id) {
      const s = this._hass && this._hass.states[id];
      return s && s.attributes ? (s.attributes.nvidia_gpu_device || s.attributes.device_id) : undefined;
    }
    _friendly(id) {
      const s = this._hass && this._hass.states[id];
      return s && s.attributes ? s.attributes.friendly_name : id;
    }

    // Group this integration's sensors by (section, device).
    // Preferred: the "nvidia_gpu_section" attribute the sensors expose (HA
    // does not put device_id on state objects, so grouping must not rely on
    // that alone). Fallback for sensors without the attribute (old
    // sensor.py): group by device and classify by which keys are present.
    _groups() {
      const states = (this._hass && this._hass.states) || {};
      let ids = (this._config && this._config.entities) || [];
      if (!ids.length) {
        ids = Object.keys(states).filter(
          (id) => id.startsWith("sensor.") && this._key(id) !== undefined
        );
      }
      const valid = ids.filter((id) => this._key(id) !== undefined);
      const out = [];
      if (valid.some((id) => this._section(id) !== undefined)) {
        // ---- new path: explicit section attribute ----
        const byGroup = new Map();
        for (const id of valid) {
          const section = this._section(id);
          const dev = this._device(id) || "_gpu";
          const gkey = section + "||" + dev;
          if (!byGroup.has(gkey)) byGroup.set(gkey, { section, firstId: id, map: {} });
          byGroup.get(gkey).map[this._key(id)] = id;
        }
        for (const g of byGroup.values()) {
          const isGpu = g.section !== "cpu";
          out.push({ isGpu, title: this._friendly(g.firstId) || (isGpu ? "GPU" : "CPU"),
                     map: g.map, metrics: isGpu ? GPU_METRICS : SYS_METRICS });
        }
      } else {
        // ---- legacy path: no section attribute, classify by keys ----
        const byDevice = new Map();
        for (const id of valid) {
          const dev = this._device(id) || "_gpu";
          if (!byDevice.has(dev)) byDevice.set(dev, { firstId: id, map: {} });
          byDevice.get(dev).map[this._key(id)] = id;
        }
        for (const g of byDevice.values()) {
          const isGpu = "gpu_utilization_pct" in g.map;
          out.push({ isGpu, title: this._friendly(g.firstId) || (isGpu ? "GPU" : "CPU"),
                     map: g.map, metrics: isGpu ? GPU_METRICS : SYS_METRICS });
        }
      }
      out.sort((a, b) => (a.isGpu === b.isGpu ? a.title.localeCompare(b.title) : (a.isGpu ? -1 : 1)));
      return out;
    }

    _card(spec, entityId) {
      const s = this._hass && this._hass.states[entityId];
      const raw = s ? parseFloat(s.state) : NaN;
      const hasValue = s && s.state !== "unknown" && s.state !== "unavailable" && isFinite(raw);
      const frac = hasValue ? Math.max(0, Math.min(1, (raw - spec.min) / (spec.max - spec.min))) : 0;

      // color: last band whose threshold is <= the value, else neutral accent
      let color = ACCENT;
      if (hasValue && spec.bands) {
        color = spec.bands[spec.bands.length - 1][1];
        for (const [t, c] of spec.bands) {
          if (raw >= t) color = c;
        }
      }

      const el = document.createElement("div");
      el.className = "card";

      const head = document.createElement("div");
      head.className = "head";
      const icon = document.createElement("span");
      icon.className = "icon";
      icon.style.color = color;
      icon.innerHTML =
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" ' +
        'stroke-linecap="round" stroke-linejoin="round"><path d="' + spec.icon + '"/></svg>';
      const tlab = document.createElement("span");
      tlab.className = "tlabel";
      tlab.textContent = spec.label;
      head.append(icon, tlab);
      el.appendChild(head);

      const val = document.createElement("div");
      val.className = "value";
      val.textContent = hasValue ? (s.state + " " + spec.unit) : ("— " + spec.unit);
      if (hasValue) val.style.color = color;
      el.appendChild(val);

      const track = document.createElement("div");
      track.className = "track";
      const fill = document.createElement("div");
      fill.className = "fill";
      fill.style.width = (frac * 100).toFixed(1) + "%";
      fill.style.background = color;
      track.appendChild(fill);
      el.appendChild(track);

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
      const section = (this._config && this._config.section) || "all";
      const shown = groups.filter((g) => section === "all" || (section === "gpu" ? g.isGpu : !g.isGpu));
      if (!shown.length) {
        const e = document.createElement("div");
        e.className = "empty";
        e.textContent = "Aucun capteur nvidia_gpu détecté";
        e.textContent += section === "gpu" ? " (GPU)." : section === "cpu" ? " (CPU)." : ".";
        root.appendChild(e);
        return;
      }
      for (const g of shown) {
        const dev = document.createElement("div");
        dev.className = "device";
        const dt = document.createElement("div");
        dt.className = "dtitle";
        const dot = document.createElement("span");
        dot.className = "dot";
        dot.style.background = g.isGpu ? DOT_GPU : DOT_SYS;
        dt.appendChild(dot);
        const dtxt = document.createElement("span");
        dtxt.textContent = g.title;
        dt.appendChild(dtxt);
        dev.appendChild(dt);
        const grid = document.createElement("div");
        grid.className = "grid";
        for (const spec of g.metrics) {
          const id = g.map[spec.key];
          if (id) grid.appendChild(this._card(spec, id));
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
      const slabel = document.createElement("label");
      slabel.style.display = "block"; slabel.style.margin = "12px 0 6px";
      slabel.textContent = "Section";
      const select = document.createElement("select");
      select.style.width = "100%"; select.style.padding = "8px"; select.style.boxSizing = "border-box";
      for (const [val, txt] of [["all", "GPU + CPU (tout)"], ["gpu", "GPU uniquement"], ["cpu", "CPU / RAM uniquement"]]) {
        const opt = document.createElement("option");
        opt.value = val; opt.textContent = txt;
        if ((this._config.section || "all") === val) opt.selected = true;
        select.appendChild(opt);
      }
      select.onchange = () => {
        this._config = { ...this._config, section: select.value === "all" ? undefined : select.value };
        this.dispatchEvent(new CustomEvent("config-changed", { detail: { config: this._config } }));
      };
      const help = document.createElement("div");
      help.style.marginTop = "10px"; help.style.fontSize = ".85em";
      help.style.color = "var(--secondary-text-color,#666)";
      help.innerHTML = "La carte détecte automatiquement les capteurs de l'intégration " +
        "<b>nvidia_gpu</b> (GPU + CPU/RAM) sur toutes vos machines, et les rend en " +
        "cartes « valeur + barre » colorées par niveau. Titre et section sont facultatifs — " +
        "utilisez « CPU / RAM uniquement » pour une carte CPU séparée.";
      wrap.append(label, input, slabel, select, help);
      this.appendChild(wrap);
    }
  }

  customElements.define("nvidia-gpu-card", NvCard);
  customElements.define("nvidia-gpu-card-editor", NvCardEditor);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "nvidia-gpu-card",
    name: "NVIDIA GPU Stats",
    description: "Métriques GPU + CPU/RAM de l'intégration nvidia_gpu (multi-GPU / multi-serveur, carte GPU ou CPU seule via « section »).",
    preview: true,
    documentationUrl: "https://github.com/thomasbidou/NVIDIA_GPU_Metric",
  });
})();
