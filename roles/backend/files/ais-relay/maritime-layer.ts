import {
  Viewer,
  Entity,
  Cartesian3,
  Color,
  NearFarScalar,
  DistanceDisplayCondition,
  Math as CesiumMath,
  HeightReference,
} from "cesium";
import { VesselState, fetchVessels } from "./maritime-api";
import { SCALE } from "@/layers/scale-constants";

const CATEGORY_COLORS: Record<string, Color> = {
  cargo:     Color.fromCssColorString("#4FC3F7"),
  tanker:    Color.fromCssColorString("#FF7043"),
  passenger: Color.fromCssColorString("#66BB6A"),
  fishing:   Color.fromCssColorString("#FFB300"),
  military:  Color.fromCssColorString("#EF5350"),
  hsc:       Color.fromCssColorString("#CE93D8"),
  special:   Color.fromCssColorString("#78909C"),
  other:     Color.fromCssColorString("#9E9E9E"),
};

export class MaritimeLayer {
  private entities = new Map<string, Entity>();
  private pollInterval: number | null = null;
  private _visible = true;

  constructor(private viewer: Viewer) {}

  async start(): Promise<void> {
    await this.update();
    this.pollInterval = window.setInterval(() => this.update(), 30_000);
  }

  private async update(): Promise<void> {
    try {
      const vessels = await fetchVessels();
      const seen = new Set<string>();

      for (const v of vessels) {
        seen.add(v.mmsi);
        const color = CATEGORY_COLORS[v.category] || CATEGORY_COLORS.other;
        const label = v.name || v.mmsi;
        const speedLabel = v.sog > 0.5 ? ` ${v.sog.toFixed(1)}kn` : "";

        const existing = this.entities.get(v.mmsi);
        if (existing) {
          (existing.position as any).setValue(
            Cartesian3.fromDegrees(v.lon, v.lat, 0)
          );
          if (existing.label) {
            (existing.label.text as any).setValue(label + speedLabel);
          }
          if (existing.properties) {
            (existing.properties as any).sog = v.sog;
            (existing.properties as any).cog = v.cog;
            (existing.properties as any).heading = v.heading;
            (existing.properties as any).destination = v.destination;
          }
        } else {
          const entity = this.viewer.entities.add({
            name: label,
            position: Cartesian3.fromDegrees(v.lon, v.lat, 0),
            point: {
              pixelSize: 5,
              color,
              outlineColor: Color.BLACK,
              outlineWidth: 1,
              scaleByDistance: SCALE.maritime.point,
              distanceDisplayCondition: SCALE.maritime.pointDisplay,
              heightReference: HeightReference.CLAMP_TO_GROUND,
            },
            label: {
              text: label + speedLabel,
              font: "9px monospace",
              fillColor: color,
              showBackground: true,
              backgroundColor: Color.fromAlpha(Color.BLACK, 0.6),
              pixelOffset: new Cartesian3(0, -14, 0) as any,
              scaleByDistance: SCALE.maritime.label,
              distanceDisplayCondition: SCALE.maritime.labelDisplay,
            },
            show: this._visible,
            properties: {
              type: "vessel",
              mmsi: v.mmsi,
              category: v.category,
              sog: v.sog,
              cog: v.cog,
              heading: v.heading,
              destination: v.destination,
              length: v.length,
              navStatus: v.navStatus,
            } as any,
          });

          this.entities.set(v.mmsi, entity);
        }
      }

      // Remove stale entities
      for (const [mmsi, entity] of this.entities) {
        if (!seen.has(mmsi)) {
          this.viewer.entities.remove(entity);
          this.entities.delete(mmsi);
        }
      }

      this.viewer.scene.requestRender();
    } catch (err) {
      console.warn("[Maritime] Update failed:", err);
    }
  }

  setVisible(visible: boolean): void {
    this._visible = visible;
    for (const entity of this.entities.values()) {
      entity.show = visible;
    }
    this.viewer.scene.requestRender();
  }

  get visible(): boolean {
    return this._visible;
  }

  get count(): number {
    return this.entities.size;
  }

  destroy(): void {
    if (this.pollInterval !== null) clearInterval(this.pollInterval);
    for (const entity of this.entities.values()) {
      this.viewer.entities.remove(entity);
    }
    this.entities.clear();
  }
}
