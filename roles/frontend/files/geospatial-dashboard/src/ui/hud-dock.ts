// Bottom HUD dock — the command bar. Groups the controls that were scattered
// or missing: audio, live filters (quake magnitude / threat origin / flights),
// tile quality, and a cinematic "hide all HUD" for a clean globe.
import { LayerManager } from "@/layers/layer-manager";
import { setTileQuality, TileQuality } from "@/globe/viewer";
import { worldAudio } from "@/audio/engine";

const store = {
  get<T>(k: string, fallback: T): T {
    try { const v = localStorage.getItem(k); return v === null ? fallback : JSON.parse(v) as T; }
    catch { return fallback; }
  },
  set(k: string, v: unknown) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* noop */ } },
};

const MAG_STEPS = [0, 2.5, 4, 5, 6];
const FLIGHT_MODES = ["all", "civil", "mil"] as const;

export class HUDDock {
  private dock: HTMLDivElement;
  private hidden = false;
  private onHideAll: (hidden: boolean) => void = () => {};

  constructor(private layers: LayerManager) {
    this.dock = document.createElement("div");
    Object.assign(this.dock.style, {
      position: "absolute", bottom: "0", left: "50%", transform: "translateX(-50%)",
      display: "flex", gap: "14px", alignItems: "center", flexWrap: "wrap",
      justifyContent: "center", maxWidth: "96vw",
      background: "rgba(4,10,8,0.82)", border: "1px solid #12331f",
      borderBottom: "none", borderRadius: "6px 6px 0 0",
      padding: "6px 14px", fontFamily: '"Courier New", monospace',
      fontSize: "10px", color: "#33ff33", zIndex: "1000",
      backdropFilter: "blur(6px)", userSelect: "none",
      transition: "transform 300ms ease, opacity 300ms ease",
    });
    this.build();
    document.body.appendChild(this.dock);
  }

  setOnHideAll(fn: (hidden: boolean) => void): void { this.onHideAll = fn; }

  private group(label: string): HTMLDivElement {
    const g = document.createElement("div");
    Object.assign(g.style, { display: "flex", alignItems: "center", gap: "5px" });
    const l = document.createElement("span");
    l.textContent = label;
    Object.assign(l.style, { fontSize: "8px", letterSpacing: "1.5px", opacity: "0.5" });
    g.appendChild(l);
    return g;
  }

  private btn(text: string, onClick: () => void, active = false): HTMLButtonElement {
    const b = document.createElement("button");
    b.textContent = text;
    Object.assign(b.style, {
      background: active ? "rgba(0,80,0,0.75)" : "rgba(0,40,0,0.45)",
      border: `1px solid ${active ? "#33ff33" : "#1a3a1a"}`,
      color: active ? "#fff" : "#33ff33",
      fontFamily: '"Courier New", monospace', fontSize: "10px",
      padding: "3px 7px", cursor: "pointer", borderRadius: "2px",
    });
    b.addEventListener("click", () => { worldAudio.ui(); onClick(); });
    return b;
  }

  private segmented<T extends string | number>(
    label: string, options: { value: T; text: string }[],
    initial: T, onChange: (v: T) => void,
  ): HTMLDivElement {
    const g = this.group(label);
    const btns = new Map<T, HTMLButtonElement>();
    let current = initial;
    const paint = () => {
      for (const [v, b] of btns) {
        const on = v === current;
        b.style.background = on ? "rgba(0,80,0,0.75)" : "rgba(0,40,0,0.45)";
        b.style.border = `1px solid ${on ? "#33ff33" : "#1a3a1a"}`;
        b.style.color = on ? "#fff" : "#33ff33";
      }
    };
    for (const opt of options) {
      const b = this.btn(opt.text, () => { current = opt.value; paint(); onChange(opt.value); });
      btns.set(opt.value, b);
      g.appendChild(b);
    }
    paint();
    return g;
  }

  private build(): void {
    // ── Audio ────────────────────────────────────────────────────────────
    const audioGroup = this.group("AUDIO");
    const armBtn = this.btn("🔊 ARM", () => {
      if (worldAudio.arm()) { armBtn.remove(); audioGroup.append(muteBtn, ambientBtn, vol); }
    });
    const muteBtn = this.btn(worldAudio.muted ? "MUTED" : "SFX", () => {
      worldAudio.setMuted(!worldAudio.muted);
      muteBtn.textContent = worldAudio.muted ? "MUTED" : "SFX";
    }, !worldAudio.muted);
    const ambientBtn = this.btn("AMBIENT", () => {
      const on = worldAudio.toggleAmbient();
      ambientBtn.style.color = on ? "#fff" : "#33ff33";
      ambientBtn.style.borderColor = on ? "#33ff33" : "#1a3a1a";
    }, worldAudio.ambientOn);
    const vol = document.createElement("input");
    vol.type = "range"; vol.min = "0"; vol.max = "0.6"; vol.step = "0.02";
    vol.value = String(worldAudio.volume);
    vol.setAttribute("aria-label", "Volume");
    Object.assign(vol.style, { width: "60px", accentColor: "#33ff33" });
    vol.addEventListener("input", () => worldAudio.setVolume(parseFloat(vol.value)));
    audioGroup.appendChild(armBtn);   // ARM first; rest appear after gesture
    this.dock.appendChild(audioGroup);

    // ── Quake magnitude filter ──────────────────────────────────────────
    const savedMag = store.get<number>("wv_min_mag", 0);
    this.layers.earthquakes.setMinMagnitude(savedMag);
    this.dock.appendChild(this.segmented(
      "QUAKE ≥",
      MAG_STEPS.map((m) => ({ value: m, text: m === 0 ? "ALL" : `M${m}` })),
      savedMag,
      (m) => { store.set("wv_min_mag", m); this.layers.earthquakes.setMinMagnitude(m); },
    ));

    // ── Threat origin filter ────────────────────────────────────────────
    const savedOrigin = store.get<"all" | "local">("wv_threat_origin", "all");
    this.layers.threats.setOriginMode(savedOrigin);
    this.dock.appendChild(this.segmented(
      "THREATS",
      [{ value: "all" as const, text: "GLOBAL" }, { value: "local" as const, text: "ON US" }],
      savedOrigin,
      (v) => { store.set("wv_threat_origin", v); this.layers.threats.setOriginMode(v); },
    ));

    // ── Flight class filter ─────────────────────────────────────────────
    const savedFlight = store.get<typeof FLIGHT_MODES[number]>("wv_flight_mode", "all");
    this.applyFlightMode(savedFlight);
    this.dock.appendChild(this.segmented(
      "FLIGHTS",
      [{ value: "all" as const, text: "ALL" }, { value: "civil" as const, text: "CIVIL" },
       { value: "mil" as const, text: "MIL" }],
      savedFlight,
      (v) => { store.set("wv_flight_mode", v); this.applyFlightMode(v); },
    ));

    // ── Tile quality ────────────────────────────────────────────────────
    const savedQ = store.get<TileQuality>("wv_tile_quality", "med");
    setTileQuality(savedQ);
    this.dock.appendChild(this.segmented(
      "TILES",
      [{ value: "low" as const, text: "LOW" }, { value: "med" as const, text: "MED" },
       { value: "high" as const, text: "HIGH" }],
      savedQ,
      (q) => { store.set("wv_tile_quality", q); setTileQuality(q); },
    ));

    // ── Cinematic hide-all ──────────────────────────────────────────────
    const hideGroup = this.group("VIEW");
    hideGroup.appendChild(this.btn("⛶ CLEAN", () => this.toggleHideAll()));
    this.dock.appendChild(hideGroup);
  }

  private applyFlightMode(mode: typeof FLIGHT_MODES[number]): void {
    // mil layer is a separate layer; civil = flights on, military off.
    if (mode === "all") { this.layers.flights.setVisible(true); this.layers.military.setVisible(true); }
    else if (mode === "civil") { this.layers.flights.setVisible(true); this.layers.military.setVisible(false); }
    else { this.layers.flights.setVisible(false); this.layers.military.setVisible(true); }
  }

  toggleHideAll(): void {
    this.hidden = !this.hidden;
    this.onHideAll(this.hidden);
    // Dock slides down but leaves a peek tab so it's recoverable.
    this.dock.style.transform = this.hidden
      ? "translateX(-50%) translateY(calc(100% - 6px))"
      : "translateX(-50%)";
    this.dock.style.opacity = this.hidden ? "0.15" : "1";
  }

  get isHidden(): boolean { return this.hidden; }
}
