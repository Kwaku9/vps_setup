import {
  Viewer,
  Entity,
  Cartesian3,
  Color,
  NearFarScalar,
  DistanceDisplayCondition,
  Math as CesiumMath,
  VerticalOrigin,
  HorizontalOrigin,
} from "cesium";

function flameSvg(hexColor: string): string {
  return `data:image/svg+xml,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="32" height="32">
    <path d="M16 2 C16 2 10 12 10 18 C10 22 12 26 16 28 C20 26 22 22 22 18 C22 12 16 2 16 2 Z M16 8 C16 8 20 14 20 18 C20 20 18 22 16 24 C14 22 12 20 12 18 C12 14 16 8 16 8 Z"
      fill="${hexColor}" stroke="#4a1a00" stroke-width="0.5" fill-rule="evenodd"/>
  </svg>`)}`;
}

const FLAME_HIGH = flameSvg("#FF3333");
const FLAME_NOMINAL = flameSvg("#FF8800");
const FLAME_LOW = flameSvg("#FF6600");
import { fetchFIRMS, ThermalAnomaly } from "./firms-api";

const ALT_THRESHOLD = 5000000; // 5000km

export class FIRMSLayer {
  private entities: Entity[] = [];
  private _visible = true;
  private loaded = false;
  private lastBBox: [number, number, number, number] | null = null;
  private refreshInterval: number | null = null;

  constructor(private viewer: Viewer) {
    const toRemove: Entity[] = [];
    for (let i = 0; i < viewer.entities.values.length; i++) {
      const e = viewer.entities.values[i] as any;
      try {
        if (e.properties?.type?.getValue() === "firms") toRemove.push(e);
      } catch (_) {}
    }
    for (const e of toRemove) viewer.entities.remove(e);
  }

  async load(): Promise<void> {
    this.loaded = true;
    // Auto-refresh every 15 minutes
    this.refreshInterval = window.setInterval(() => {
      if (this._visible && this.lastBBox) {
        this.fetchAndRender(...this.lastBBox);
      }
    }, 900000);
    console.log("FIRMS layer initialized (camera-aware, loads below 5000km)");
  }

  onCameraMove(): void {
    if (!this._visible || !this.loaded) return;

    const carto = this.viewer.camera.positionCartographic;
    const alt = carto.height;

    if (alt > ALT_THRESHOLD) {
      this.clearEntities();
      return;
    }

    const lat = CesiumMath.toDegrees(carto.latitude);
    const lon = CesiumMath.toDegrees(carto.longitude);

    // Compute bbox based on altitude
    const spanDeg = Math.min(20, Math.max(2, (alt / 1000000) * 10));
    const west = lon - spanDeg;
    const east = lon + spanDeg;
    const south = lat - spanDeg;
    const north = lat + spanDeg;

    // Skip if bbox hasn't shifted much
    if (this.lastBBox) {
      const [lw, ls, le, ln] = this.lastBBox;
      if (
        Math.abs(lw - west) < 0.5 &&
        Math.abs(ls - south) < 0.5 &&
        Math.abs(le - east) < 0.5 &&
        Math.abs(ln - north) < 0.5
      ) {
        return;
      }
    }

    this.lastBBox = [west, south, east, north];
    this.fetchAndRender(west, south, east, north);
  }

  private async fetchAndRender(
    west: number,
    south: number,
    east: number,
    north: number
  ): Promise<void> {
    try {
      const anomalies = await fetchFIRMS(west, south, east, north);
      this.clearEntities();

      for (const a of anomalies) {
        if (!a.latitude || !a.longitude) continue;

        const size = Math.max(4, Math.min(16, Math.sqrt(a.frp) * 2));
        const confLower = a.confidence.toLowerCase();
        const color =
          confLower === "high" || confLower === "h"
            ? Color.RED
            : confLower === "nominal" || confLower === "n"
              ? Color.ORANGE
              : Color.fromCssColorString("#FF6600");

        const entity = this.viewer.entities.add({
          name: `Fire ${a.frp.toFixed(1)} MW`,
          position: Cartesian3.fromDegrees(a.longitude, a.latitude, 100),
          billboard: {
            image: confLower === "high" || confLower === "h" ? FLAME_HIGH
                 : confLower === "nominal" || confLower === "n" ? FLAME_NOMINAL
                 : FLAME_LOW,
            width: size * 2.5,
            height: size * 2.5,
            verticalOrigin: VerticalOrigin.BOTTOM,
            horizontalOrigin: HorizontalOrigin.CENTER,
            scaleByDistance: new NearFarScalar(1e5, 2.0, 5e7, 0.3),
            distanceDisplayCondition: new DistanceDisplayCondition(0, 5e7),
          },
          label: {
            text: a.frp.toFixed(0) + " MW",
            font: "9px monospace",
            fillColor: Color.YELLOW,
            showBackground: true,
            backgroundColor: Color.fromAlpha(Color.BLACK, 0.7),
            pixelOffset: new Cartesian3(0, -14, 0) as any,
            scaleByDistance: new NearFarScalar(1e5, 1, 5e6, 0.2),
            distanceDisplayCondition: new DistanceDisplayCondition(0, 5e6),
          },
          show: this._visible,
          properties: {
            type: "firms",
            brightness: a.brightness,
            confidence: a.confidence,
            frp: a.frp,
            satellite: a.satellite,
            acqDate: a.acq_date,
            acqTime: a.acq_time,
            daynight: a.daynight,
          } as any,
        });

        this.entities.push(entity);
      }

      if (anomalies.length > 0) {
        this.viewer.scene.requestRender();
        console.log("Loaded " + anomalies.length + " FIRMS anomalies");
      }
    } catch (e) {
      console.warn("FIRMS load failed:", e);
    }
  }

  private clearEntities(): void {
    for (const e of this.entities) {
      this.viewer.entities.remove(e);
    }
    this.entities = [];
  }

  setVisible(visible: boolean): void {
    this._visible = visible;
    if (!visible) {
      this.clearEntities();
    } else {
      // Re-fetch: clear lastBBox so onCameraMove triggers a fresh load
      this.lastBBox = null;
      this.onCameraMove();
    }
    this.viewer.scene.requestRender();
  }

  get visible(): boolean {
    return this._visible;
  }

  get count(): number {
    return this.entities.length;
  }

  destroy(): void {
    if (this.refreshInterval !== null) clearInterval(this.refreshInterval);
    this.clearEntities();
  }
}
