import {
  Viewer,
  Entity,
  Cartesian3,
  Color,
  DistanceDisplayCondition,
  NearFarScalar,
  CallbackProperty,
  VerticalOrigin,
  HorizontalOrigin,
  Math as CesiumMath,
} from "cesium";

function quakeSvg(hexColor: string): string {
  return `data:image/svg+xml,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="32" height="32">
    <circle cx="16" cy="16" r="6" fill="${hexColor}" opacity="0.9" stroke="${hexColor}" stroke-width="2" stroke-opacity="0.4"/>
    <circle cx="16" cy="16" r="10" fill="none" stroke="${hexColor}" stroke-width="1.5" opacity="0.5"/>
    <circle cx="16" cy="16" r="14" fill="none" stroke="${hexColor}" stroke-width="1" opacity="0.25"/>
  </svg>`)}`;
}
import { Earthquake, fetchEarthquakes } from "./earthquake-api";

function magnitudeColor(mag: number): Color {
  if (mag < 4) return Color.fromCssColorString("#22ff22");
  if (mag < 5.5) return Color.YELLOW;
  if (mag < 7) return Color.ORANGE;
  return Color.RED;
}

function magnitudePixelSize(mag: number): number {
  // Scale pixel size by magnitude: 4px for M2.5, up to 20px for M8+
  return Math.max(4, Math.min(20, mag * 2.5));
}

export class EarthquakeLayer {
  private entities: Entity[] = [];
  private refreshInterval: number | null = null;
  private _visible = true;

  constructor(private viewer: Viewer) {
    const toRemove: Entity[] = [];
    for (let i = 0; i < viewer.entities.values.length; i++) {
      const e = viewer.entities.values[i] as any;
      try {
        if (e.properties?.type?.getValue() === "earthquake") toRemove.push(e);
      } catch (_) {}
    }
    for (const e of toRemove) viewer.entities.remove(e);
  }

  async load(): Promise<void> {
    await this.update();
    this.refreshInterval = window.setInterval(() => this.update(), 300000);
  }

  onCameraMove(): void {
    if (!this._visible) return;
    this.update();
  }

  private async update(): Promise<void> {
    try {
      const allQuakes = await fetchEarthquakes();

      // Filter to viewport
      const cam = this.viewer.camera.positionCartographic;
      const lat = CesiumMath.toDegrees(cam.latitude);
      const lon = CesiumMath.toDegrees(cam.longitude);
      const alt = cam.height;
      const spanDeg = Math.min(90, Math.max(2, (alt / 1000000) * 15));
      const quakes = allQuakes.filter(q => {
        const dLat = Math.abs(q.latitude - lat);
        const dLon = Math.abs(q.longitude - lon);
        return dLat < spanDeg && dLon < spanDeg;
      });

      for (const e of this.entities) {
        this.viewer.entities.remove(e);
      }
      this.entities = [];

      for (const q of quakes) {
        const color = magnitudeColor(q.magnitude);
        const size = magnitudePixelSize(q.magnitude);

        const entity = this.viewer.entities.add({
          name: "M" + q.magnitude.toFixed(1) + " - " + q.place,
          position: Cartesian3.fromDegrees(q.longitude, q.latitude, 0),
          billboard: {
            image: quakeSvg(magnitudeColor(q.magnitude).toCssColorString()),
            width: size * 3,
            height: size * 3,
            verticalOrigin: VerticalOrigin.CENTER,
            horizontalOrigin: HorizontalOrigin.CENTER,
            scaleByDistance: new NearFarScalar(1e5, 2, 1e8, 0.5),
            distanceDisplayCondition: new DistanceDisplayCondition(0, 5e7),
          },
          label: {
            text: "M" + q.magnitude.toFixed(1),
            font: "10px monospace",
            fillColor: color,
            showBackground: true,
            backgroundColor: Color.fromAlpha(Color.BLACK, 0.6),
            pixelOffset: new Cartesian3(0, -14, 0) as any,
            scaleByDistance: new NearFarScalar(1e5, 1, 1e7, 0.3),
            distanceDisplayCondition: new DistanceDisplayCondition(0, 5e6),
          },
          show: this._visible,
          properties: {
            type: "earthquake",
            magnitude: q.magnitude,
            depth: q.depth,
            place: q.place,
            time: q.time,
            tsunami: q.tsunami,
            url: q.url,
          } as any,
        });

        this.entities.push(entity);
      }

      this.viewer.scene.requestRender();
      console.log("Loaded " + quakes.length + " earthquakes");
    } catch (e) {
      console.warn("Earthquake update failed:", e);
    }
  }

  setVisible(visible: boolean): void {
    this._visible = visible;
    for (const e of this.entities) {
      e.show = visible;
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
    for (const e of this.entities) {
      this.viewer.entities.remove(e);
    }
    this.entities = [];
  }
}
