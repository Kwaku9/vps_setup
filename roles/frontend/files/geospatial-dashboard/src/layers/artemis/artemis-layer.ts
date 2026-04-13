import {
  Viewer,
  Entity,
  Cartesian3,
  Color,
  NearFarScalar,
  CallbackProperty,
  PolylineDashMaterialProperty,
  PolylineGlowMaterialProperty,
  HeightReference,
  ConstantPositionProperty,
} from "cesium";
import {
  ArtemisData,
  TrajectoryPoint,
  fetchArtemisTrajectory,
  interpolatePosition,
  getMissionPhase,
  getHoursAfterLaunch,
  LAUNCH_TIME,
  MISSION_EVENTS,
  KSC_LAT,
  KSC_LON,
} from "./artemis-api";

const ARTEMIS_COLOR = Color.fromCssColorString("#00BFFF"); // deep sky blue
const TRAIL_COLOR = Color.fromCssColorString("#FF6B35");    // orange trail (past)
const LEAD_COLOR = Color.fromCssColorString("#00BFFF");     // blue lead (future)
const MOON_COLOR = Color.fromCssColorString("#C0C0C0");     // silver

// Max display altitude in meters — caps polyline positions to avoid CesiumJS frustum overflow.
// Spacecraft/Moon point entities can exceed this (single points are fine); polylines cannot.
const MAX_POLYLINE_ALT = 120_000_000; // 120,000 km — covers TLI + coast, clips at deep lunar

function clampAlt(alt: number): number {
  return Math.min(alt, MAX_POLYLINE_ALT);
}

export class ArtemisLayer {
  private spacecraft: Entity | null = null;
  private moonEntity: Entity | null = null;
  private trailEntity: Entity | null = null;
  private leadEntity: Entity | null = null;
  private trajectoryData: ArtemisData | null = null;
  private updateInterval: number | null = null;
  private pulsePhase = 0;
  private _visible = true;
  private _count = 0;

  constructor(private viewer: Viewer) {}

  async load(): Promise<void> {
    try {
      this.trajectoryData = await fetchArtemisTrajectory();
      const scLen = this.trajectoryData.spacecraft.length;
      const moonLen = this.trajectoryData.moon.length;
      console.log(
        `Artemis 2: loaded ${scLen} SC points, ${moonLen} Moon points. Phase: ${this.trajectoryData.missionPhase}`
      );

      this.createEntities();
      this.updatePositions();

      // Update current position every 5 seconds
      this.updateInterval = window.setInterval(() => {
        this.updatePositions();
        this.pulsePhase += 0.3;
      }, 5000);

      // Refresh trajectory from Horizons every 30 minutes
      window.setInterval(() => this.refreshTrajectory(), 30 * 60000);

    } catch (err) {
      console.warn("Artemis 2 layer failed to load:", err);
    }
  }

  private createEntities(): void {
    if (!this.trajectoryData) return;

    // Initial position: KSC if pre-launch, or first trajectory point
    const initPos = this.getCurrentPosition();

    // --- Spacecraft entity (pulsing) ---
    this.spacecraft = this.viewer.entities.add({
      name: "ARTEMIS II - Orion",
      position: Cartesian3.fromDegrees(initPos.lon, initPos.lat, initPos.alt),
      point: {
        pixelSize: new CallbackProperty(() => {
          return 12 + 4 * Math.sin(this.pulsePhase);
        }, false) as any,
        color: ARTEMIS_COLOR,
        outlineColor: Color.WHITE,
        outlineWidth: 2,
        disableDepthTestDistance: Number.POSITIVE_INFINITY,
        heightReference: HeightReference.NONE,
      },
      label: {
        text: new CallbackProperty(() => {
          return this.buildLabel();
        }, false) as any,
        font: "12px monospace",
        fillColor: ARTEMIS_COLOR,
        showBackground: true,
        backgroundColor: Color.fromAlpha(Color.BLACK, 0.85),
        pixelOffset: new Cartesian3(0, -30, 0) as any,
        scaleByDistance: new NearFarScalar(1e6, 1.2, 5e8, 0.5),
        disableDepthTestDistance: Number.POSITIVE_INFINITY,
      },
      properties: {
        type: "artemis",
        mission: "Artemis II",
      } as any,
    });

    // --- Moon entity ---
    const moonPos = this.getCurrentMoonPosition();
    this.moonEntity = this.viewer.entities.add({
      name: "Moon",
      position: Cartesian3.fromDegrees(moonPos.lon, moonPos.lat, moonPos.alt),
      point: {
        pixelSize: 14,
        color: MOON_COLOR,
        outlineColor: Color.fromCssColorString("#888888"),
        outlineWidth: 2,
        disableDepthTestDistance: Number.POSITIVE_INFINITY,
        heightReference: HeightReference.NONE,
      },
      label: {
        text: "MOON",
        font: "10px monospace",
        fillColor: MOON_COLOR,
        showBackground: true,
        backgroundColor: Color.fromAlpha(Color.BLACK, 0.6),
        pixelOffset: new Cartesian3(0, -18, 0) as any,
        scaleByDistance: new NearFarScalar(1e7, 1, 5e8, 0.4),
        disableDepthTestDistance: Number.POSITIVE_INFINITY,
      },
      properties: {
        type: "artemis",
        body: "Moon",
      } as any,
    });

    // --- Trajectory trail (past path - solid orange) ---
    // Use static positions, updated every 5s in updatePositions()
    this.trailEntity = this.viewer.entities.add({
      name: "Artemis II trail",
      polyline: {
        positions: [],
        width: 3,
        material: new PolylineGlowMaterialProperty({
          glowPower: 0.2,
          color: TRAIL_COLOR.withAlpha(0.7),
        }),
      },
      properties: { type: "artemis-trail" } as any,
    });

    // --- Trajectory lead (future path - dashed blue) ---
    this.leadEntity = this.viewer.entities.add({
      name: "Artemis II prediction",
      polyline: {
        positions: [],
        width: 2,
        material: new PolylineDashMaterialProperty({
          color: LEAD_COLOR.withAlpha(0.4),
          dashLength: 16,
        }),
      },
      properties: { type: "artemis-lead" } as any,
    });

    this._count = 2; // spacecraft + moon
  }

  private getCurrentPosition(): { lat: number; lon: number; alt: number } {
    const now = new Date();
    const hoursAfterLaunch = getHoursAfterLaunch(now);
    const data = this.trajectoryData;

    // Before launch: show at KSC
    if (hoursAfterLaunch < 0) {
      return { lat: KSC_LAT, lon: KSC_LON, alt: 0 };
    }

    // During ascent (before trajectory data): interpolate altitude from ground to first trajectory point
    if (data && data.spacecraft.length > 0 && hoursAfterLaunch < MISSION_EVENTS.icpsSeparation) {
      const firstPoint = data.spacecraft[0];
      const ascentFraction = hoursAfterLaunch / MISSION_EVENTS.icpsSeparation;
      const easedFrac = ascentFraction * ascentFraction * ascentFraction;
      const alt = firstPoint.alt * easedFrac;
      const lat = KSC_LAT + (firstPoint.lat - KSC_LAT) * ascentFraction;
      const lon = KSC_LON + (firstPoint.lon - KSC_LON) * ascentFraction;
      return { lat, lon, alt };
    }

    // During mission: use trajectory data
    if (data && data.spacecraft.length > 0) {
      const pos = interpolatePosition(data.spacecraft, now);
      if (pos) return { lat: pos.lat, lon: pos.lon, alt: pos.alt };
    }

    return { lat: KSC_LAT, lon: KSC_LON, alt: 0 };
  }

  private getCurrentMoonPosition(): { lat: number; lon: number; alt: number } {
    const now = new Date();
    const data = this.trajectoryData;
    if (data && data.moon.length > 0) {
      const pos = interpolatePosition(data.moon, now);
      if (pos) return { lat: pos.lat, lon: pos.lon, alt: pos.alt };
    }
    return { lat: 0, lon: 0, alt: 384400000 };
  }

  private buildLabel(): string {
    const now = new Date();
    const phase = getMissionPhase(now);
    const hoursAfterLaunch = getHoursAfterLaunch(now);

    if (hoursAfterLaunch < 0) {
      const launchDate = new Date(LAUNCH_TIME);
      const msUntil = launchDate.getTime() - now.getTime();
      const hrsUntil = Math.floor(msUntil / 3600000);
      const minsUntil = Math.floor((msUntil % 3600000) / 60000);
      return `ARTEMIS II - Orion "Integrity"\n${phase}\nT-${hrsUntil}h${minsUntil.toString().padStart(2, "0")}m to Launch\nKennedy Space Center LC-39B`;
    }

    const pos = this.getCurrentPosition();
    const altKm = pos.alt / 1000;
    const tHrs = Math.floor(hoursAfterLaunch);
    const tMins = Math.floor((hoursAfterLaunch % 1) * 60);

    const data = this.trajectoryData;
    let speedStr = "";
    let rangeStr = "";
    if (data && data.spacecraft.length > 0) {
      const scPos = interpolatePosition(data.spacecraft, now);
      if (scPos) {
        speedStr = ` | SPD: ${scPos.speed.toFixed(1)} km/s`;
        rangeStr = `\nRNG: ${this.formatDistance(scPos.range)}`;
      }
    }

    return `ARTEMIS II - Orion "Integrity"\n${phase} | T+${tHrs}h${tMins.toString().padStart(2, "0")}m\nALT: ${this.formatDistance(altKm)}${speedStr}${rangeStr}`;
  }

  private updatePositions(): void {
    if (!this.spacecraft || !this.moonEntity) return;

    const now = new Date();

    // Update spacecraft position (point entity — no altitude cap)
    const scPos = this.getCurrentPosition();
    (this.spacecraft.position as unknown as ConstantPositionProperty).setValue(
      Cartesian3.fromDegrees(scPos.lon, scPos.lat, scPos.alt)
    );

    // Update Moon position (point entity — no altitude cap)
    const moonPos = this.getCurrentMoonPosition();
    (this.moonEntity.position as unknown as ConstantPositionProperty).setValue(
      Cartesian3.fromDegrees(moonPos.lon, moonPos.lat, moonPos.alt)
    );

    // Update trail and lead polylines (altitude-capped to avoid frustum overflow)
    this.updatePaths(now);

    this.viewer.scene.requestRender();
  }

  private updatePaths(now: Date): void {
    if (!this.trajectoryData) return;
    const data = this.trajectoryData;
    const t = now.getTime();

    // Trail: points before now, altitude capped
    const trailPoints = data.spacecraft
      .filter((p) => p.epoch.getTime() <= t)
      .map((p) => Cartesian3.fromDegrees(p.lon, p.lat, clampAlt(p.alt)));

    if (this.trailEntity?.polyline) {
      (this.trailEntity.polyline.positions as any) = trailPoints;
    }

    // Lead: points after now, altitude capped
    const leadPoints = data.spacecraft
      .filter((p) => p.epoch.getTime() > t)
      .map((p) => Cartesian3.fromDegrees(p.lon, p.lat, clampAlt(p.alt)));

    if (this.leadEntity?.polyline) {
      (this.leadEntity.polyline.positions as any) = leadPoints;
    }
  }

  private formatDistance(km: number): string {
    if (km < 1000) return km.toFixed(0) + " km";
    return (km / 1000).toFixed(1) + "K km";
  }

  private async refreshTrajectory(): Promise<void> {
    try {
      const newData = await fetchArtemisTrajectory();
      if (newData.spacecraft.length > 0) {
        this.trajectoryData = newData;
        console.log("Artemis 2: trajectory refreshed, phase:", newData.missionPhase);
      }
    } catch (err) {
      console.warn("Artemis 2 trajectory refresh failed:", err);
    }
  }

  setVisible(visible: boolean): void {
    this._visible = visible;
    const entities = [
      this.spacecraft,
      this.moonEntity,
      this.trailEntity,
      this.leadEntity,
    ];
    for (const entity of entities) {
      if (entity) entity.show = visible;
    }
    this.viewer.scene.requestRender();
  }

  get visible(): boolean {
    return this._visible;
  }

  get count(): number {
    return this._count;
  }

  destroy(): void {
    if (this.updateInterval !== null) clearInterval(this.updateInterval);
    const entities = [
      this.spacecraft,
      this.moonEntity,
      this.trailEntity,
      this.leadEntity,
    ];
    for (const entity of entities) {
      if (entity) this.viewer.entities.remove(entity);
    }
    this.spacecraft = null;
    this.moonEntity = null;
    this.trailEntity = null;
    this.leadEntity = null;
    this._count = 0;
  }
}
