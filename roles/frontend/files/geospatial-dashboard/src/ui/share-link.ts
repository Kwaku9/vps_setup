// Share links, after God's Eye View (github.com/bilawalsidhu/gods-eye-view,
// MIT): camera, layers, vision mode and the tracked target serialize into the
// URL. A tracked threat is written as its IP and a POI as its key, so the
// link reopens locked on the same target (and orbiting, if it was).
import { Viewer, Math as CesiumMath } from "cesium";
import { LayerManager, LAYER_NAMES, LayerName } from "@/layers/layer-manager";
import { ShaderManager, VisionMode } from "@/shaders/postprocess";
import { TargetLock, TiltMode } from "@/globe/target-lock";

const VISION_MODES: VisionMode[] = ["normal", "crt", "nvg", "flir"];

export interface ShareParams {
  track: string | null;
  /** POI key when the view is locked on a point of interest. */
  poi: string | null;
  orbit: boolean;
  range: number;
  heading: number;
  tilt: TiltMode | null;
  cam: { lon: number; lat: number; height: number; heading: number; pitch: number } | null;
  layers: LayerName[] | null;
  mode: VisionMode | null;
}

/** Parse the share-link part of a query string. Unknown or malformed values
 *  are ignored, so a hand-edited link degrades to the default view. */
export function readShareParams(search: string): ShareParams {
  const p = new URLSearchParams(search);
  const num = (v: string | null) => (v === null || v === "" ? NaN : Number(v));

  let cam: ShareParams["cam"] = null;
  const camParts = (p.get("cam") ?? "").split(",").map(Number);
  if (camParts.length === 5 && camParts.every(Number.isFinite)) {
    const [lon, lat, height, heading, pitch] = camParts;
    cam = { lon, lat, height, heading, pitch };
  }

  const layersRaw = p.get("layers");
  const layers =
    layersRaw === null
      ? null
      : (layersRaw.split(",").filter((n) =>
          (LAYER_NAMES as string[]).includes(n)
        ) as LayerName[]);

  const modeRaw = p.get("mode") as VisionMode | null;
  const tiltRaw = p.get("tilt");

  return {
    track: p.get("track"),
    poi: p.get("poi"),
    orbit: p.get("orbit") === "1",
    range: num(p.get("range")),
    heading: num(p.get("hdg")),
    tilt: tiltRaw === "top" || tiltRaw === "oblique" ? tiltRaw : null,
    cam,
    layers,
    mode: modeRaw && VISION_MODES.includes(modeRaw) ? modeRaw : null,
  };
}

export class ShareLink {
  private lastQuery = "";
  private toast: HTMLDivElement;

  constructor(
    private viewer: Viewer,
    private layers: LayerManager,
    private shaders: ShaderManager,
    private lock: TargetLock
  ) {
    this.toast = document.createElement("div");
    Object.assign(this.toast.style, {
      position: "absolute",
      bottom: "calc(90px + env(safe-area-inset-bottom, 0px))",
      left: "50%",
      transform: "translateX(-50%)",
      background: "rgba(0,0,0,0.9)",
      border: "1px solid #33ff33",
      color: "#33ff33",
      fontFamily: '"Courier New", monospace',
      fontSize: "11px",
      padding: "6px 10px",
      zIndex: "1002",
      maxWidth: "90vw",
      wordBreak: "break-all",
    });
    this.toast.hidden = true;
    document.body.appendChild(this.toast);
  }

  /** Keep the address bar in step with the view, so reload or a copied URL
   *  reopens it. replaceState: no history entry per camera move. */
  startSync(): void {
    const sync = () => this.syncURL();
    this.viewer.camera.moveEnd.addEventListener(sync);
    this.lock.onChange(sync);
    // Layer and vision toggles come from several panels and keys; a cheap
    // poll catches all of them without wiring each one.
    window.setInterval(sync, 2000);
    sync();
  }

  url(): string {
    return `${location.origin}${location.pathname}?${this.query()}`;
  }

  async copy(): Promise<void> {
    const url = this.url();
    try {
      await navigator.clipboard.writeText(url);
      this.flash("LINK COPIED");
    } catch {
      // Clipboard can be refused (permissions, insecure context): show the
      // link so it can be copied by hand.
      this.flash(url, 8000);
    }
  }

  private syncURL(): void {
    const q = this.query();
    if (q === this.lastQuery) return;
    this.lastQuery = q;
    history.replaceState(null, "", `${location.pathname}?${q}`);
  }

  private query(): string {
    const p = new URLSearchParams();
    // The country filter is part of the view; keep it.
    const country = this.layers.threats.countryFilterActive;
    if (country) p.set("country", country);

    const lock = this.lock.current;
    if (lock) {
      if (lock.target.kind === "threat") p.set("track", lock.id);
      else p.set("poi", lock.target.key);
      p.set("range", String(Math.round(lock.range)));
      p.set("hdg", lock.heading.toFixed(1));
      p.set("tilt", this.lock.tilt ?? "oblique");
      if (lock.orbiting) p.set("orbit", "1");
    } else {
      const cam = this.viewer.camera;
      const c = cam.positionCartographic;
      p.set(
        "cam",
        [
          CesiumMath.toDegrees(c.longitude).toFixed(5),
          CesiumMath.toDegrees(c.latitude).toFixed(5),
          Math.round(c.height),
          CesiumMath.toDegrees(cam.heading).toFixed(1),
          CesiumMath.toDegrees(cam.pitch).toFixed(1),
        ].join(",")
      );
    }

    p.set(
      "layers",
      LAYER_NAMES.filter((n) => this.layers[n].visible).join(",")
    );
    const mode = this.shaders.getMode();
    if (mode !== "normal") p.set("mode", mode);
    // Keep commas readable; URLSearchParams escapes them.
    return p.toString().replace(/%2C/g, ",");
  }

  private flash(text: string, ms = 1800): void {
    this.toast.textContent = text;
    this.toast.hidden = false;
    window.setTimeout(() => (this.toast.hidden = true), ms);
  }
}
