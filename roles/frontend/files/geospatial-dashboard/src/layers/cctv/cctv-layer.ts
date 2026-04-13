import {
  Viewer,
  Entity,
  Cartesian3,
  Color,
  NearFarScalar,
  DistanceDisplayCondition,
  VerticalOrigin,
} from "cesium";
import { fetchCameras, getSnapshotUrl, CCTVCamera } from "./cctv-api";

/** City-level POI for CCTV coverage areas */
interface CCTVCity {
  name: string;
  lat: number;
  lon: number;
  cameraCount: number;
}

export class CCTVLayer {
  private entities: Entity[] = [];
  private cityEntities: Entity[] = [];
  private _visible = true;

  constructor(private viewer: Viewer) {
    const toRemove: Entity[] = [];
    for (let i = 0; i < viewer.entities.values.length; i++) {
      const e = viewer.entities.values[i] as any;
      try {
        if (e.properties?.type?.getValue() === "cctv") toRemove.push(e);
      } catch (_) {}
    }
    for (const e of toRemove) viewer.entities.remove(e);
  }

  async load(): Promise<void> {
    try {
      const cameras = await fetchCameras();

      // Group cameras by city to create city-level POIs
      const cityMap = new Map<string, { lat: number; lon: number; count: number }>();
      for (const cam of cameras) {
        const cityKey = this.normalizeCityKey(cam.city);
        const existing = cityMap.get(cityKey);
        if (existing) {
          // Running average of coordinates for city center
          existing.lat = (existing.lat * existing.count + cam.lat) / (existing.count + 1);
          existing.lon = (existing.lon * existing.count + cam.lon) / (existing.count + 1);
          existing.count++;
        } else {
          cityMap.set(cityKey, { lat: cam.lat, lon: cam.lon, count: 1 });
        }
      }

      // Create city-level POI markers (visible from far away)
      for (const [cityName, info] of cityMap) {
        const displayName = cityName;
        const cityEntity = this.viewer.entities.add({
          name: `CCTV: ${displayName}`,
          position: Cartesian3.fromDegrees(info.lon, info.lat, 500),
          billboard: {
            image: this.createCCTVCityIcon(info.count),
            width: 32,
            height: 32,
            verticalOrigin: VerticalOrigin.BOTTOM,
            scaleByDistance: new NearFarScalar(1e4, 1.5, 1e7, 0.4),
            distanceDisplayCondition: new DistanceDisplayCondition(5e4, 2e7),
          },
          label: {
            text: `${displayName}\n${info.count} cameras`,
            font: "11px monospace",
            fillColor: Color.fromCssColorString("#ff4444"),
            outlineColor: Color.BLACK,
            outlineWidth: 2,
            style: 2, // FILL_AND_OUTLINE
            showBackground: true,
            backgroundColor: Color.fromAlpha(Color.BLACK, 0.75),
            pixelOffset: new Cartesian3(0, -40, 0) as any,
            scaleByDistance: new NearFarScalar(1e4, 1.2, 5e6, 0.3),
            distanceDisplayCondition: new DistanceDisplayCondition(5e4, 1e7),
          },
          show: this._visible,
          properties: {
            type: "cctv-city",
            city: cityName,
            cameraCount: info.count,
          } as any,
        });
        this.cityEntities.push(cityEntity);
      }

      // Create individual camera markers (visible when zoomed in)
      for (const cam of cameras) {
        const entity = this.viewer.entities.add({
          name: cam.name,
          position: Cartesian3.fromDegrees(cam.lon, cam.lat, 30),
          point: {
            pixelSize: 8,
            color: Color.RED,
            outlineColor: Color.WHITE,
            outlineWidth: 2,
            scaleByDistance: new NearFarScalar(1e3, 2, 1e6, 0.5),
            distanceDisplayCondition: new DistanceDisplayCondition(0, 5e5),
          },
          label: {
            text: cam.name,
            font: "9px monospace",
            fillColor: Color.RED,
            showBackground: true,
            backgroundColor: Color.fromAlpha(Color.BLACK, 0.7),
            pixelOffset: new Cartesian3(0, -16, 0) as any,
            scaleByDistance: new NearFarScalar(1e3, 1, 1e5, 0.3),
            distanceDisplayCondition: new DistanceDisplayCondition(0, 5e4),
          },
          show: this._visible,
          properties: {
            type: "cctv",
            cameraId: cam.id,
            snapshotUrl: getSnapshotUrl(cam),
            city: cam.city,
            direction: cam.direction,
          } as any,
        });

        this.entities.push(entity);
      }

      console.log(
        `CCTV: ${cameras.length} cameras across ${cityMap.size} cities`
      );
    } catch (e) {
      console.warn("CCTV camera load failed:", e);
    }
  }

  /** Normalize city names into consistent keys */
  private normalizeCityKey(city: string): string {
    const c = city.trim();
    if (c === "NYC") return "New York City";
    if (c === "FL") return "Florida";
    if (c === "Los Angeles") return "Los Angeles";
    if (c === "GA") return "Georgia";
    if (c === "DC") return "Washington DC";
    if (c === "Illinois") return "Illinois";
    return c || "Unknown";
  }

  /** Create a canvas-based CCTV city icon */
  private createCCTVCityIcon(count: number): HTMLCanvasElement {
    const size = 32;
    const canvas = document.createElement("canvas");
    canvas.width = size;
    canvas.height = size;
    const ctx = canvas.getContext("2d")!;

    // Red circle with camera count
    ctx.beginPath();
    ctx.arc(size / 2, size / 2, size / 2 - 2, 0, Math.PI * 2);
    ctx.fillStyle = "rgba(255, 30, 30, 0.85)";
    ctx.fill();
    ctx.strokeStyle = "#ffffff";
    ctx.lineWidth = 2;
    ctx.stroke();

    // Camera icon (simple rectangle + lens)
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(8, 10, 12, 8);
    ctx.beginPath();
    ctx.moveTo(20, 11);
    ctx.lineTo(25, 9);
    ctx.lineTo(25, 19);
    ctx.lineTo(20, 17);
    ctx.closePath();
    ctx.fill();

    // Count badge
    ctx.fillStyle = "#ffffff";
    ctx.font = "bold 8px monospace";
    ctx.textAlign = "center";
    ctx.fillText(count > 999 ? (count / 1000).toFixed(1) + "k" : String(count), size / 2, 28);

    return canvas;
  }

  setVisible(visible: boolean): void {
    this._visible = visible;
    for (const e of this.entities) {
      e.show = visible;
    }
    for (const e of this.cityEntities) {
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
    for (const e of this.entities) {
      this.viewer.entities.remove(e);
    }
    for (const e of this.cityEntities) {
      this.viewer.entities.remove(e);
    }
    this.entities = [];
    this.cityEntities = [];
  }
}
