import {
  Viewer,
  Entity,
  Cartesian3,
  Color,
  Math as CesiumMath,
} from "cesium";
import { fetchAllWigle, WigleNetwork } from "./wigle-api";
import { WigleHeatmap } from "./wigle-heatmap";
import { SCALE } from "@/layers/scale-constants";

function encryptionColor(enc: string, type: string): Color {
  if (type === "cell") return Color.CYAN;
  if (type === "bt") return Color.MAGENTA;
  const e = enc.toLowerCase();
  if (e.includes("none") || e === "unknown" || e === "") return Color.RED;
  if (e.includes("wep")) return Color.ORANGE;
  if (e.includes("wpa")) return Color.fromCssColorString("#22ff22");
  return Color.YELLOW;
}

function typeIcon(type: string): string {
  if (type === "cell") return "CELL";
  if (type === "bt") return "BT";
  return "WiFi";
}

const POINT_ALT = 5000;     // Below 5km: individual points
const HEATMAP_ALT = 50000;  // 5km-50km: heatmap mode

export class WigleLayer {
  private entities: Entity[] = [];
  private _visible = true;
  private loaded = false;
  private heatmap: WigleHeatmap;

  constructor(private viewer: Viewer) {
    this.heatmap = new WigleHeatmap(viewer);
  }

  async load(): Promise<void> {
    this.loaded = true;
    console.log("WiGLE layer initialized (camera-aware, heatmap 5-50km, points <5km)");
  }

  onCameraMove(): void {
    if (!this._visible || !this.loaded) return;

    const carto = this.viewer.camera.positionCartographic;
    const alt = carto.height;

    if (alt > HEATMAP_ALT) {
      // Too high for WiGLE
      this.clearEntities();
      this.heatmap.deactivate();
      return;
    }

    const lat = CesiumMath.toDegrees(carto.latitude);
    const lon = CesiumMath.toDegrees(carto.longitude);

    if (alt > POINT_ALT) {
      // Heatmap mode: 5km-50km
      this.clearEntities();
      const radiusKm = Math.min(10, Math.max(2, alt / 5000));
      this.fetchForHeatmap(lat, lon, radiusKm);
    } else {
      // Point mode: <5km
      this.heatmap.deactivate();
      const radiusKm = Math.min(2, Math.max(0.5, alt / 5000));
      this.fetchAndRender(lat, lon, radiusKm);
    }
  }

  private async fetchForHeatmap(
    lat: number,
    lon: number,
    radiusKm: number
  ): Promise<void> {
    try {
      const networks = await fetchAllWigle(lat, lon, radiusKm);
      this.heatmap.setNetworks(networks);
      this.heatmap.activate();
      if (networks.length > 0) {
        console.log("WiGLE heatmap: " + networks.length + " networks");
      }
    } catch (e) {
      console.warn("WiGLE heatmap fetch failed:", e);
    }
  }

  private async fetchAndRender(
    lat: number,
    lon: number,
    radiusKm: number
  ): Promise<void> {
    try {
      const networks = await fetchAllWigle(lat, lon, radiusKm);
      this.clearEntities();

      for (const net of networks) {
        if (!net.lat || !net.lon) continue;

        const color = encryptionColor(net.encryption, net.type);
        const size = net.type === "cell" ? 7 : net.type === "bt" ? 4 : 5;
        const label = typeIcon(net.type) + " " + net.ssid;

        const entity = this.viewer.entities.add({
          name: label,
          position: Cartesian3.fromDegrees(net.lon, net.lat, 10),
          point: {
            pixelSize: size,
            color: color.withAlpha(0.8),
            outlineColor: color,
            outlineWidth: 1,
            scaleByDistance: SCALE.wigle.point,
            distanceDisplayCondition: SCALE.wigle.pointDisplay,
          },
          label: {
            text: net.ssid.length > 20 ? net.ssid.substring(0, 20) + "..." : net.ssid,
            font: "8px monospace",
            fillColor: color,
            showBackground: true,
            backgroundColor: Color.fromAlpha(Color.BLACK, 0.7),
            pixelOffset: new Cartesian3(0, -12, 0) as any,
            scaleByDistance: SCALE.wigle.label,
            distanceDisplayCondition: SCALE.wigle.labelDisplay,
          },
          show: this._visible,
          properties: {
            type: "wigle",
            netType: net.type,
            ssid: net.ssid,
            bssid: net.bssid,
            encryption: net.encryption,
            channel: net.channel,
            firstSeen: net.firstSeen,
            lastSeen: net.lastSeen,
            carrier: net.carrier || "",
            cellType: net.cellType || "",
          } as any,
        });

        this.entities.push(entity);
      }

      if (networks.length > 0) {
        this.viewer.scene.requestRender();
        console.log("Loaded " + networks.length + " WiGLE networks");
      }
    } catch (e) {
      console.warn("WiGLE load failed:", e);
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
    for (const e of this.entities) {
      e.show = visible;
    }
    if (!visible) {
      this.clearEntities();
      this.heatmap.deactivate();
    }
    this.viewer.scene.requestRender();
  }

  get visible(): boolean {
    return this._visible;
  }

  get count(): number {
    return this.entities.length + (this.heatmap.active ? 1 : 0);
  }

  destroy(): void {
    this.clearEntities();
    this.heatmap.destroy();
  }
}
