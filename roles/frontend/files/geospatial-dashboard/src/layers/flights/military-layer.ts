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
import { MilitaryAircraft, fetchMilitaryAircraft } from "./adsb-api";
import { aircraftIcon, classifyAircraft, northAxis } from "@/globe/icons";

// Military tint (amber) over the white class silhouettes.
const MILITARY_TINT = Color.fromCssColorString("#FF8C00");

export class MilitaryLayer {
  private entities = new Map<string, Entity>();
  private pollInterval: number | null = null;
  private _visible = true;
  // Latched so an unavailable upstream is explained once, not on every poll.
  private warnedUnavailable = false;

  constructor(private viewer: Viewer) {
    const toRemove: Entity[] = [];
    for (let i = 0; i < viewer.entities.values.length; i++) {
      const e = viewer.entities.values[i] as any;
      try {
        if (e.properties?.type?.getValue() === "military") toRemove.push(e);
      } catch (_) {}
    }
    for (const e of toRemove) viewer.entities.remove(e);
  }

  async start(): Promise<void> {
    await this.update();
    // Poll every 30 seconds
    this.pollInterval = window.setInterval(() => this.update(), 30000);
  }

  private async update(): Promise<void> {
    try {
      const aircraft = await fetchMilitaryAircraft();
      const seen = new Set<string>();

      for (const ac of aircraft) {
        seen.add(ac.icao);

        const existing = this.entities.get(ac.icao);
        const position = Cartesian3.fromDegrees(ac.longitude, ac.latitude, ac.altitude);
        if (existing) {
          (existing.position as any).setValue(position);
          if (existing.billboard) {
            (existing.billboard.rotation as any).setValue(
              CesiumMath.toRadians(-(ac.heading || 0))
            );
            (existing.billboard.alignedAxis as any).setValue(northAxis(position));
          }
          if (existing.properties) {
            (existing.properties as any).altitude = ac.altitude;
            (existing.properties as any).speed = ac.speed;
            (existing.properties as any).heading = ac.heading;
          }
        } else {
          const baseLabel = ac.callsign || ac.type || ac.icao;
          const flLabel = baseLabel + " FL" + Math.round(ac.altitude * 3.28084 / 100);

          const entity = this.viewer.entities.add({
            name: baseLabel,
            position,
            billboard: {
              // Military feed carries ICAO type codes, so the class is exact.
              image: aircraftIcon(classifyAircraft({ typeCode: ac.type === "Unknown" ? "" : ac.type })),
              color: MILITARY_TINT,
              width: 22,
              height: 22,
              rotation: CesiumMath.toRadians(-(ac.heading || 0)),
              alignedAxis: northAxis(position),
              verticalOrigin: VerticalOrigin.CENTER,
              horizontalOrigin: HorizontalOrigin.CENTER,
              scaleByDistance: new NearFarScalar(1e5, 1.5, 5e6, 0.3),
              distanceDisplayCondition: new DistanceDisplayCondition(0, 4e7),
            },
            label: {
              text: flLabel,
              font: "10px monospace",
              fillColor: Color.ORANGE,
              showBackground: true,
              backgroundColor: Color.fromAlpha(Color.BLACK, 0.6),
              pixelOffset: new Cartesian3(0, -14, 0) as any,
              scaleByDistance: new NearFarScalar(1e5, 1, 5e6, 0.3),
              distanceDisplayCondition: new DistanceDisplayCondition(0, 5e6),
            },
            show: this._visible,
            properties: {
              type: "military",
              icao: ac.icao,
              callsign: ac.callsign,
              aircraftType: ac.type,
              description: ac.description,
              operator: ac.operator,
              altitude: ac.altitude,
              speed: ac.speed,
              heading: ac.heading,
              squawk: ac.squawk,
            } as any,
          });

          this.entities.set(ac.icao, entity);
        }
      }

      // Remove stale
      for (const [icao, entity] of this.entities) {
        if (!seen.has(icao)) {
          this.viewer.entities.remove(entity);
          this.entities.delete(icao);
        }
      }

      this.viewer.scene.requestRender();
    } catch (e) {
      // An unavailable feed is expected for anyone without airplanes.live
      // approval, so say why once rather than repeating a stack trace on every
      // poll. The layer simply stays empty.
      if ((e as Error)?.name === 'MilitaryFeedUnavailable') {
        if (!this.warnedUnavailable) {
          console.warn(`Military layer inactive — ${(e as Error).message}`);
          this.warnedUnavailable = true;
        }
      } else {
        console.warn("Military aircraft update failed:", e);
      }
    }
  }

  setVisible(visible: boolean): void {
    this._visible = visible;
    if (visible) {
      this.update();
    } else {
      for (const entity of this.entities.values()) {
        entity.show = false;
      }
      this.viewer.scene.requestRender();
    }
  }

  get visible(): boolean {
    return this._visible;
  }

  get count(): number {
    return this.entities.size;
  }

  destroy(): void {
    if (this.pollInterval !== null) {
      clearInterval(this.pollInterval);
    }
    for (const entity of this.entities.values()) {
      this.viewer.entities.remove(entity);
    }
    this.entities.clear();
  }
}
