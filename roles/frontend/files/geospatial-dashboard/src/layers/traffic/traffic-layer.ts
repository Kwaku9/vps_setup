import {
  Viewer,
  Cartesian3,
  Color,
  Math as CesiumMath,
  PointPrimitiveCollection,
  PointPrimitive,
} from "cesium";
import { fetchRoadSegments, RoadSegment } from "./overpass-api";

interface Particle {
  segment: RoadSegment;
  progress: number; // 0-1 along the segment
  speed: number; // meters per second
  point: PointPrimitive;
}

const MAX_PARTICLES = 500;
const ALT_THRESHOLD = 50000; // 50km

function roadColor(highway: string): Color {
  if (highway === "motorway") return Color.YELLOW;
  if (highway === "primary") return Color.WHITE;
  return Color.fromCssColorString("#999999");
}

function baseSpeed(highway: string): number {
  if (highway === "motorway") return 30;
  if (highway === "primary") return 20;
  return 12;
}

function interpolatePosition(
  segment: RoadSegment,
  progress: number
): [number, number] {
  const dist = progress * segment.totalLength;
  const cumLens = segment.cumulativeLengths;

  let i = 1;
  while (i < cumLens.length && cumLens[i] < dist) i++;

  if (i >= segment.coords.length) {
    return segment.coords[segment.coords.length - 1];
  }

  const segStart = cumLens[i - 1];
  const segEnd = cumLens[i];
  const segLen = segEnd - segStart;
  const t = segLen > 0 ? (dist - segStart) / segLen : 0;

  const [lon1, lat1] = segment.coords[i - 1];
  const [lon2, lat2] = segment.coords[i];
  return [lon1 + (lon2 - lon1) * t, lat1 + (lat2 - lat1) * t];
}

export class TrafficLayer {
  private points: PointPrimitiveCollection;
  private particles: Particle[] = [];
  private _visible = true;
  private removePostUpdate: (() => void) | null = null;
  private loaded = false;

  constructor(private viewer: Viewer) {
    this.points = new PointPrimitiveCollection();
    viewer.scene.primitives.add(this.points);

    // Animation loop via postUpdate
    const cb = () => this.animate();
    viewer.scene.postUpdate.addEventListener(cb);
    this.removePostUpdate = () =>
      viewer.scene.postUpdate.removeEventListener(cb);
  }

  async load(): Promise<void> {
    this.loaded = true;
    console.log("Traffic layer initialized (camera-aware, loads on zoom)");
  }

  onCameraMove(): void {
    if (!this._visible || !this.loaded) return;

    const carto = this.viewer.camera.positionCartographic;
    const alt = carto.height;

    if (alt > ALT_THRESHOLD) {
      this.clearParticles();
      return;
    }

    const lat = CesiumMath.toDegrees(carto.latitude);
    const lon = CesiumMath.toDegrees(carto.longitude);
    const radiusKm = Math.min(5, Math.max(1, alt / 10000));

    this.loadSegments(lat, lon, radiusKm);
  }

  private async loadSegments(
    lat: number,
    lon: number,
    radiusKm: number
  ): Promise<void> {
    try {
      const segments = await fetchRoadSegments(lat, lon, radiusKm);
      this.clearParticles();

      if (segments.length === 0) return;

      const particlesPerSegment = Math.max(
        1,
        Math.floor(MAX_PARTICLES / segments.length)
      );

      for (const seg of segments) {
        const count = Math.min(
          particlesPerSegment,
          Math.ceil(seg.totalLength / 100)
        );
        for (let j = 0; j < count; j++) {
          if (this.particles.length >= MAX_PARTICLES) break;

          const progress = Math.random();
          const speed =
            baseSpeed(seg.highway) * (0.7 + Math.random() * 0.6);
          const color = roadColor(seg.highway);
          const [pLon, pLat] = interpolatePosition(seg, progress);

          const point = this.points.add({
            position: Cartesian3.fromDegrees(pLon, pLat, 5),
            pixelSize: seg.highway === "motorway" ? 4 : 3,
            color,
            show: this._visible,
          });

          this.particles.push({ segment: seg, progress, speed, point });
        }
      }
    } catch (e) {
      console.warn("Traffic load failed:", e);
    }
  }

  private animate(): void {
    if (!this._visible || this.particles.length === 0) return;

    const dt = 1 / 60; // approximate frame time

    for (const p of this.particles) {
      const progressDelta = (p.speed * dt) / p.segment.totalLength;
      p.progress += progressDelta;

      // Wrap around at end
      if (p.progress >= 1) p.progress -= 1;

      const [pLon, pLat] = interpolatePosition(p.segment, p.progress);
      p.point.position = Cartesian3.fromDegrees(pLon, pLat, 5);
    }
  }

  private clearParticles(): void {
    this.points.removeAll();
    this.particles = [];
  }

  setVisible(visible: boolean): void {
    this._visible = visible;
    for (const p of this.particles) {
      p.point.show = visible;
    }
    if (!visible) {
      this.clearParticles();
    }
    this.viewer.scene.requestRender();
  }

  get visible(): boolean {
    return this._visible;
  }

  get count(): number {
    return this.particles.length;
  }

  destroy(): void {
    if (this.removePostUpdate) this.removePostUpdate();
    this.viewer.scene.primitives.remove(this.points);
    this.particles = [];
  }
}
