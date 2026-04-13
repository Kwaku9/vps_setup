import {
  Viewer,
  Entity,
  SampledPositionProperty,
  JulianDate,
  Cartesian3,
  Color,
  Math as CesiumMath,
  PolylineDashMaterialProperty,
} from "cesium";
import {
  propagate,
  gstime,
  eciToGeodetic,
  SatRec,
  EciVec3,
} from "satellite.js";

export class OrbitRenderer {
  private orbitEntities: Entity[] = [];
  private issTrailEntity: Entity | null = null;
  private issLeadEntity: Entity | null = null;

  constructor(private viewer: Viewer) {}

  renderOrbit(satrec: SatRec, name: string): void {
    const positionProperty = new SampledPositionProperty();
    const now = new Date();
    const samples = 180;

    const meanMotion = satrec.no;
    const periodMinutes = (2 * Math.PI) / meanMotion;
    const stepMinutes = periodMinutes / samples;

    for (let i = 0; i <= samples; i++) {
      const time = new Date(now.getTime() + i * stepMinutes * 60000);
      const gmst = gstime(time);
      const result = propagate(satrec, time);

      if (!result.position || typeof result.position === "boolean") continue;

      const positionEci = result.position as EciVec3<number>;
      const geodetic = eciToGeodetic(positionEci, gmst);

      const lon = CesiumMath.toDegrees(geodetic.longitude);
      const lat = CesiumMath.toDegrees(geodetic.latitude);
      const alt = geodetic.height * 1000;

      const julianDate = JulianDate.fromDate(time);
      positionProperty.addSample(
        julianDate,
        Cartesian3.fromDegrees(lon, lat, alt)
      );
    }

    const predictionPositions: Cartesian3[] = [];
    const predMinutes = 90;
    const predSteps = 60;
    const predStep = predMinutes / predSteps;

    for (let i = 0; i <= predSteps; i++) {
      const time = new Date(now.getTime() + i * predStep * 60000);
      const gmst = gstime(time);
      const result = propagate(satrec, time);

      if (!result.position || typeof result.position === "boolean") continue;

      const positionEci = result.position as EciVec3<number>;
      const geodetic = eciToGeodetic(positionEci, gmst);

      const lon = CesiumMath.toDegrees(geodetic.longitude);
      const lat = CesiumMath.toDegrees(geodetic.latitude);
      const alt = geodetic.height * 1000;

      predictionPositions.push(Cartesian3.fromDegrees(lon, lat, alt));
    }

    const orbitEntity = this.viewer.entities.add({
      name: name + " orbit",
      position: positionProperty,
      path: {
        resolution: 120,
        material: Color.CYAN.withAlpha(0.3),
        width: 1,
        leadTime: periodMinutes * 60,
        trailTime: periodMinutes * 60,
      },
      properties: {
        type: "orbit",
      } as any,
    });

    this.orbitEntities.push(orbitEntity);

    if (predictionPositions.length > 1) {
      const predEntity = this.viewer.entities.add({
        name: name + " prediction",
        polyline: {
          positions: predictionPositions,
          width: 1,
          material: new PolylineDashMaterialProperty({
            color: Color.YELLOW.withAlpha(0.5),
            dashLength: 8,
          }),
        },
        properties: {
          type: "prediction",
        } as any,
      });
      this.orbitEntities.push(predEntity);
    }
  }

  /** Render ISS-specific orbit with 45-min red trail behind + 45-min gold dashed lead ahead */
  renderISSOrbit(satrec: SatRec, _name: string): void {
    this.buildISSOrbit(satrec);
  }

  /** Rebuild ISS orbit positions (called every 30s to make trail/lead move) */
  updateISSOrbit(satrec: SatRec): void {
    if (this.issTrailEntity) {
      this.viewer.entities.remove(this.issTrailEntity);
      const idx = this.orbitEntities.indexOf(this.issTrailEntity);
      if (idx >= 0) this.orbitEntities.splice(idx, 1);
      this.issTrailEntity = null;
    }
    if (this.issLeadEntity) {
      this.viewer.entities.remove(this.issLeadEntity);
      const idx = this.orbitEntities.indexOf(this.issLeadEntity);
      if (idx >= 0) this.orbitEntities.splice(idx, 1);
      this.issLeadEntity = null;
    }
    this.buildISSOrbit(satrec);
  }

  private buildISSOrbit(satrec: SatRec): void {
    const now = new Date();
    const samples = 90;
    const minutesSpan = 45;
    const stepMin = minutesSpan / samples;

    // Trail: 45 minutes behind current position (solid red)
    const trailPositions: Cartesian3[] = [];
    for (let i = samples; i >= 0; i--) {
      const time = new Date(now.getTime() - i * stepMin * 60000);
      const pos = this.propagateToCartesian(satrec, time);
      if (pos) trailPositions.push(pos);
    }

    if (trailPositions.length > 1) {
      this.issTrailEntity = this.viewer.entities.add({
        name: "ISS trail",
        polyline: {
          positions: trailPositions,
          width: 2,
          material: Color.RED.withAlpha(0.6),
        },
        properties: { type: "orbit" } as any,
      });
      this.orbitEntities.push(this.issTrailEntity);
    }

    // Lead: 45 minutes ahead (dashed gold)
    const leadPositions: Cartesian3[] = [];
    for (let i = 0; i <= samples; i++) {
      const time = new Date(now.getTime() + i * stepMin * 60000);
      const pos = this.propagateToCartesian(satrec, time);
      if (pos) leadPositions.push(pos);
    }

    if (leadPositions.length > 1) {
      this.issLeadEntity = this.viewer.entities.add({
        name: "ISS prediction",
        polyline: {
          positions: leadPositions,
          width: 2,
          material: new PolylineDashMaterialProperty({
            color: Color.GOLD.withAlpha(0.6),
            dashLength: 12,
          }),
        },
        properties: { type: "prediction" } as any,
      });
      this.orbitEntities.push(this.issLeadEntity);
    }
  }

  private propagateToCartesian(satrec: SatRec, time: Date): Cartesian3 | null {
    const gmst = gstime(time);
    const result = propagate(satrec, time);
    if (!result.position || typeof result.position === "boolean") return null;

    const positionEci = result.position as EciVec3<number>;
    const geodetic = eciToGeodetic(positionEci, gmst);

    const lon = CesiumMath.toDegrees(geodetic.longitude);
    const lat = CesiumMath.toDegrees(geodetic.latitude);
    const alt = geodetic.height * 1000;

    return Cartesian3.fromDegrees(lon, lat, alt);
  }

  setVisible(visible: boolean): void {
    for (const entity of this.orbitEntities) {
      entity.show = visible;
    }
  }

  destroy(): void {
    for (const entity of this.orbitEntities) {
      this.viewer.entities.remove(entity);
    }
    this.orbitEntities = [];
    this.issTrailEntity = null;
    this.issLeadEntity = null;
  }
}
