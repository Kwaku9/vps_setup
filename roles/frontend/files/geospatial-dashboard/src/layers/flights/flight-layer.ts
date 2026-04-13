import {
  Viewer,
  Entity,
  Cartesian3,
  Color,
  NearFarScalar,
  DistanceDisplayCondition,
  Math as CesiumMath,
  HeightReference,
  VerticalOrigin,
  HorizontalOrigin,
} from "cesium";
import { FlightState, fetchFlightStates } from "./opensky-api";

// Top-down airplane silhouette SVG (pointing up / north)
const AIRPLANE_SVG = `data:image/svg+xml,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="32" height="32">
  <path d="M16 2 L14 12 L4 16 L14 15 L14 26 L10 28 L14 27.5 L16 30 L18 27.5 L22 28 L18 26 L18 15 L28 16 L18 12 Z"
    fill="#00ff41" stroke="#003300" stroke-width="0.5"/>
</svg>`)}`;

export class FlightLayer {
  private entities = new Map<string, Entity>();
  private pollInterval: number | null = null;
  private _visible = true;

  constructor(private viewer: Viewer) {
    // Clean up orphaned entities from HMR reloads
    const toRemove: Entity[] = [];
    for (let i = 0; i < viewer.entities.values.length; i++) {
      const e = viewer.entities.values[i] as any;
      try {
        if (e.properties?.type?.getValue() === "flight") toRemove.push(e);
      } catch (_) {}
    }
    for (const e of toRemove) viewer.entities.remove(e);
    if (toRemove.length > 0) console.log("[Flights] Cleaned " + toRemove.length + " orphaned entities");
  }

  async start(): Promise<void> {
    await this.update();
    // Poll every 30 seconds (respects API rate limits)
    this.pollInterval = window.setInterval(() => this.update(), 30000);
  }

  private clearAll(): void {
    for (const [icao, entity] of this.entities) {
      this.viewer.entities.remove(entity);
    }
    this.entities.clear();
    this.viewer.scene.requestRender();
  }

  private async update(): Promise<void> {
    try {
      const cam = this.viewer.camera.positionCartographic;
      const lat = CesiumMath.toDegrees(cam.latitude);
      const lon = CesiumMath.toDegrees(cam.longitude);
      const alt = cam.height;

      // Don't fetch when zoomed out above 5000km
      if (alt > 5_000_000) {
        if (this.entities.size > 0) this.clearAll();
        return;
      }

      // Cap radius to 150nm to reduce data and avoid rate limits
      const radiusNm = Math.min(150, Math.max(25, alt / 10000));

      const flights = await fetchFlightStates(lat, lon, radiusNm);
      const seen = new Set<string>();

      for (const flight of flights) {
        seen.add(flight.icao24);

        const existing = this.entities.get(flight.icao24);
        if (existing) {
          (existing.position as any).setValue(
            Cartesian3.fromDegrees(
              flight.longitude,
              flight.latitude,
              flight.altitude
            )
          );
          // Update heading rotation
          if (existing.billboard) {
            (existing.billboard.rotation as any).setValue(
              CesiumMath.toRadians(-(flight.heading || 0))
            );
          }
          // Update label with current flight level
          const flLabel = flight.callsign
            ? flight.callsign + " FL" + Math.round(flight.altitude * 3.28084 / 100)
            : flight.icao24;
          if (existing.label) {
            (existing.label.text as any).setValue(flLabel);
          }
          // Update properties for info panel
          if (existing.properties) {
            (existing.properties as any).altitude = flight.altitude;
            (existing.properties as any).velocity = flight.velocity;
            (existing.properties as any).heading = flight.heading;
          }
        } else {
          const label =
            flight.callsign ||
            flight.icao24;
          const flLabel = flight.callsign
            ? flight.callsign + " FL" + Math.round(flight.altitude * 3.28084 / 100)
            : flight.icao24;

          // Show aircraft type in label if available
          const typeTag = flight.aircraftType ? ` [${flight.aircraftType}]` : '';

          const entity = this.viewer.entities.add({
            name: label + typeTag,
            position: Cartesian3.fromDegrees(
              flight.longitude,
              flight.latitude,
              flight.altitude
            ),
            billboard: {
              image: AIRPLANE_SVG,
              width: 20,
              height: 20,
              rotation: CesiumMath.toRadians(-(flight.heading || 0)),
              alignedAxis: Cartesian3.UNIT_Z,
              verticalOrigin: VerticalOrigin.CENTER,
              horizontalOrigin: HorizontalOrigin.CENTER,
              scaleByDistance: new NearFarScalar(1e5, 1.5, 5e6, 0.3),
              distanceDisplayCondition: new DistanceDisplayCondition(0, 3e7),
            },
            label: {
              text: flLabel,
              font: "9px monospace",
              fillColor: Color.fromCssColorString("#33ff33"),
              showBackground: true,
              backgroundColor: Color.fromAlpha(Color.BLACK, 0.5),
              pixelOffset: new Cartesian3(0, -12, 0) as any,
              scaleByDistance: new NearFarScalar(1e5, 1, 5e6, 0.2),
              distanceDisplayCondition: new DistanceDisplayCondition(0, 3e6),
            },
            show: this._visible,
            properties: {
              type: "flight",
              icao24: flight.icao24,
              callsign: flight.callsign,
              aircraftType: flight.aircraftType,
              description: flight.description,
              operator: flight.operator,
              altitude: flight.altitude,
              velocity: flight.velocity,
              heading: flight.heading,
            } as any,
          });

          this.entities.set(flight.icao24, entity);
        }
      }

      // Remove stale entities
      for (const [icao, entity] of this.entities) {
        if (!seen.has(icao)) {
          this.viewer.entities.remove(entity);
          this.entities.delete(icao);
        }
      }

      this.viewer.scene.requestRender();
    } catch (e) {
      console.warn("Flight update failed:", e);
    }
  }

  setVisible(visible: boolean): void {
    this._visible = visible;
    if (visible) {
      // Force immediate update to clean stale entities from old camera position
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
