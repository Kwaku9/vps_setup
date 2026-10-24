import {
  Viewer,
  Entity,
  Cartesian3,
  Color,
  NearFarScalar,
  DistanceDisplayCondition,
  Math as CesiumMath,
  HeightReference,
  Rectangle,
  VerticalOrigin,
  HorizontalOrigin,
} from "cesium";
import { VesselState, BoundingBox, fetchVessels } from "./maritime-api";
import { SCALE } from "@/layers/scale-constants";
import { classifyVessel, northAxis, vesselIcon, vesselPixelSize } from "@/globe/icons";

/** Direction to point a vessel: true heading, or course over ground when
 *  AIS reports heading as unavailable (511). */
function vesselCourse(v: VesselState): number {
  return v.heading != null && v.heading >= 0 && v.heading < 360 ? v.heading : v.cog || 0;
}

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

  constructor(private viewer: Viewer) {
    const toRemove: Entity[] = [];
    for (let i = 0; i < viewer.entities.values.length; i++) {
      const e = viewer.entities.values[i] as any;
      try {
        if (e.properties?.type?.getValue() === "vessel") toRemove.push(e);
      } catch (_) {}
    }
    for (const e of toRemove) viewer.entities.remove(e);
  }

  async start(): Promise<void> {
    await this.update();
    this.pollInterval = window.setInterval(() => this.update(), 30_000);
  }

  /** Area to request vessels for. computeViewRectangle() returns nothing
   *  whenever sky is in view (any oblique angle), and an undefined box asked
   *  the relay for EVERY ship worldwide: 2,000 entities, Danish trawlers
   *  included, for a view of Nevada. Fall back to, and cap at, a box around
   *  the camera sized by its altitude. */
  private getViewportBbox(): BoundingBox | undefined {
    const cam = this.viewer.camera.positionCartographic;
    const lat = CesiumMath.toDegrees(cam.latitude);
    const lon = CesiumMath.toDegrees(cam.longitude);
    // ~4x altitude in reach, 1°..30° half-span (1° ≈ 111 km).
    const half = Math.min(30, Math.max(1, (cam.height * 4) / 111_000));
    const halfLon = half / Math.max(0.2, Math.cos(cam.latitude));
    // The relay takes -180..180 and reads minLon > maxLon as crossing the
    // antimeridian, so wrap rather than let the box run past ±180.
    const wrap = (d: number) => ((((d + 180) % 360) + 360) % 360) - 180;
    const around: BoundingBox = {
      minLat: Math.max(-90, lat - half),
      maxLat: Math.min(90, lat + half),
      minLon: halfLon >= 180 ? -180 : wrap(lon - halfLon),
      maxLon: halfLon >= 180 ? 180 : wrap(lon + halfLon),
    };
    let rect;
    try {
      rect = this.viewer.camera.computeViewRectangle();
    } catch {
      rect = undefined;
    }
    if (!rect) return around;
    const view: BoundingBox = {
      minLat: CesiumMath.toDegrees(rect.south),
      maxLat: CesiumMath.toDegrees(rect.north),
      minLon: CesiumMath.toDegrees(rect.west),
      maxLon: CesiumMath.toDegrees(rect.east),
    };
    const spanLon = (view.maxLon - view.minLon + 360) % 360;
    // A view rectangle wider than the camera box (oblique horizon) is capped.
    return view.maxLat - view.minLat > 2 * half || spanLon > 2 * halfLon
      ? around
      : view;
  }

  private async update(): Promise<void> {
    try {
      const bbox = this.getViewportBbox();
      const vessels = await fetchVessels(bbox);
      const seen = new Set<string>();

      for (const v of vessels) {
        seen.add(v.mmsi);
        const color = CATEGORY_COLORS[v.category] || CATEGORY_COLORS.other;
        const label = v.name || v.mmsi;
        const speedLabel = v.sog > 0.5 ? ` ${v.sog.toFixed(1)}kn` : "";

        const existing = this.entities.get(v.mmsi);
        const position = Cartesian3.fromDegrees(v.lon, v.lat, 0);
        if (existing) {
          (existing.position as any).setValue(position);
          if (existing.billboard) {
            (existing.billboard.rotation as any).setValue(
              CesiumMath.toRadians(-vesselCourse(v))
            );
            (existing.billboard.alignedAxis as any).setValue(northAxis(position));
          }
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
            position,
            billboard: {
              image: vesselIcon(classifyVessel(v.shipType, v.category)),
              color: Color.fromCssColorString(v.color),
              width: vesselPixelSize(v.length),
              height: vesselPixelSize(v.length),
              rotation: CesiumMath.toRadians(-vesselCourse(v)),
              alignedAxis: northAxis(position),
              verticalOrigin: VerticalOrigin.CENTER,
              horizontalOrigin: HorizontalOrigin.CENTER,
              scaleByDistance: SCALE.maritime.point,
              distanceDisplayCondition: SCALE.maritime.pointDisplay,
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
