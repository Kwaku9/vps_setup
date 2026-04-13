import {
  Viewer,
  Entity,
  Cartesian3,
  Color,
  NearFarScalar,
  DistanceDisplayCondition,
  Math as CesiumMath,
  CallbackProperty,
} from "cesium";
import {
  twoline2satrec,
  propagate,
  gstime,
  eciToGeodetic,
  SatRec,
  EciVec3,
} from "satellite.js";
import { TLERecord, fetchAllGroups } from "./satellite-api";
import { OrbitRenderer } from "./orbit-renderer";
import { SCALE } from "@/layers/scale-constants";

const GROUP_COLORS: Record<string, Color> = {
  stations: Color.RED,
  visual:   Color.fromCssColorString("#FFB300"),
  weather:  Color.fromCssColorString("#42A5F5"),
  "gps-ops":Color.fromCssColorString("#66BB6A"),
  starlink: Color.fromCssColorString("#9E9E9E"),
  galileo:  Color.fromCssColorString("#CE93D8"),
};

interface SatelliteState {
  name: string;
  satrec: SatRec;
  entity: Entity;
  noradId: string;
  group: string;
}

export class SatelliteLayer {
  private satellites: SatelliteState[] = [];
  private updateInterval: number | null = null;
  private orbitRenderer: OrbitRenderer;
  private _visible = true;
  private issState: SatelliteState | null = null;
  private issPulsePhase = 0;

  constructor(private viewer: Viewer) {
    this.orbitRenderer = new OrbitRenderer(viewer);
  }

  get iss(): SatelliteState | null {
    return this.issState;
  }

  async load(): Promise<void> {
    const tles = await fetchAllGroups();
    console.log("Loaded " + tles.length + " TLEs from all groups");

    const seen = new Set<string>();

    for (const tle of tles) {
      const noradId = tle.line1.substring(2, 7).trim();
      if (seen.has(noradId)) continue;
      seen.add(noradId);

      const satrec = twoline2satrec(tle.line1, tle.line2);
      const color = GROUP_COLORS[tle.group] || Color.CYAN;
      const isISS = noradId === "25544";

      let entity: Entity;

      if (isISS) {
        // ISS hero entity: larger, gold outline, always visible, pulsing
        entity = this.viewer.entities.add({
          name: "ISS (ZARYA)",
          position: Cartesian3.fromDegrees(0, 0, 0),
          point: {
            pixelSize: new CallbackProperty(() => {
              return 8 + 2 * Math.sin(this.issPulsePhase);
            }, false) as any,
            color: Color.RED,
            outlineColor: Color.GOLD,
            outlineWidth: 2,
            // No distanceDisplayCondition — always visible
          },
          label: {
            text: "ISS [25544]",
            font: "12px monospace",
            fillColor: Color.GOLD,
            showBackground: true,
            backgroundColor: Color.fromAlpha(Color.BLACK, 0.7),
            pixelOffset: new Cartesian3(0, -16, 0) as any,
            scaleByDistance: new NearFarScalar(1e6, 1.2, 5e7, 0.4),
            // Always visible label
          },
          properties: {
            type: "satellite",
            noradId,
            group: tle.group,
          } as any,
        });
      } else {
        entity = this.viewer.entities.add({
          name: tle.name,
          position: Cartesian3.fromDegrees(0, 0, 0),
          point: {
            pixelSize: 4,
            color: color,
            scaleByDistance: SCALE.satellites.point,
            distanceDisplayCondition: SCALE.satellites.pointDisplay,
          },
          label: {
            text: tle.name + " [" + noradId + "]",
            font: "10px monospace",
            fillColor: color,
            showBackground: true,
            backgroundColor: Color.fromAlpha(Color.BLACK, 0.6),
            pixelOffset: new Cartesian3(0, -12, 0) as any,
            scaleByDistance: SCALE.satellites.label,
            distanceDisplayCondition: SCALE.satellites.labelDisplay,
          },
          properties: {
            type: "satellite",
            noradId,
            group: tle.group,
          } as any,
        });
      }

      const state: SatelliteState = {
        name: tle.name,
        satrec,
        entity,
        noradId,
        group: tle.group,
      };

      this.satellites.push(state);

      if (isISS) {
        this.issState = state;
      }
    }

    this.updatePositions();
    this.updateInterval = window.setInterval(() => {
      this.updatePositions();
      this.issPulsePhase += 0.3;
    }, 5000);

    // Render ISS-specific orbit (trail + lead)
    if (this.issState) {
      this.orbitRenderer.renderISSOrbit(this.issState.satrec, "ISS");
      // Start ISS orbit refresh every 30s
      window.setInterval(() => {
        if (this.issState) {
          this.orbitRenderer.updateISSOrbit(this.issState.satrec);
        }
      }, 30000);
    }

    // Render orbits for other station satellites
    const stations = this.satellites.filter(
      (s) => s.group === "stations" && s.noradId !== "25544"
    );
    for (const sat of stations.slice(0, 5)) {
      this.orbitRenderer.renderOrbit(sat.satrec, sat.name);
    }
  }

  private updatePositions(): void {
    const now = new Date();
    const gmst = gstime(now);

    for (const sat of this.satellites) {
      const result = propagate(sat.satrec, now);
      if (!result.position || typeof result.position === "boolean") continue;

      const positionEci = result.position as EciVec3<number>;
      const geodetic = eciToGeodetic(positionEci, gmst);

      const lon = CesiumMath.toDegrees(geodetic.longitude);
      const lat = CesiumMath.toDegrees(geodetic.latitude);
      const alt = geodetic.height * 1000;

      (sat.entity.position as any).setValue(
        Cartesian3.fromDegrees(lon, lat, alt)
      );
    }

    this.viewer.scene.requestRender();
  }

  setVisible(visible: boolean): void {
    this._visible = visible;
    for (const sat of this.satellites) {
      sat.entity.show = visible;
    }
    this.orbitRenderer.setVisible(visible);
    this.viewer.scene.requestRender();
  }

  get visible(): boolean {
    return this._visible;
  }

  get count(): number {
    return this.satellites.length;
  }

  destroy(): void {
    if (this.updateInterval !== null) clearInterval(this.updateInterval);
    for (const sat of this.satellites) {
      this.viewer.entities.remove(sat.entity);
    }
    this.orbitRenderer.destroy();
    this.satellites = [];
  }
}
