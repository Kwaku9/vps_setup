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

const MILITARY_SVG = `data:image/svg+xml,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="32" height="32">
  <path d="M16 1 L13 14 L2 18 L13 16.5 L13 26 L9 29 L13 28 L16 31 L19 28 L23 29 L19 26 L19 16.5 L30 18 L19 14 Z"
    fill="#FF8C00" stroke="#4a2800" stroke-width="0.7"/>
</svg>`)}`;

export class MilitaryLayer {
  private entities = new Map<string, Entity>();
  private pollInterval: number | null = null;
  private _visible = true;

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
        if (existing) {
          (existing.position as any).setValue(
            Cartesian3.fromDegrees(ac.longitude, ac.latitude, ac.altitude)
          );
          if (existing.billboard) {
            (existing.billboard.rotation as any).setValue(
              CesiumMath.toRadians(-(ac.heading || 0))
            );
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
            position: Cartesian3.fromDegrees(
              ac.longitude,
              ac.latitude,
              ac.altitude
            ),
            billboard: {
              image: MILITARY_SVG,
              width: 22,
              height: 22,
              rotation: CesiumMath.toRadians(-(ac.heading || 0)),
              alignedAxis: Cartesian3.UNIT_Z,
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
      console.warn("Military aircraft update failed:", e);
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
