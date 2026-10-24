import {
  Viewer,
  Cartesian3,
  Math as CesiumMath,
  HeadingPitchRange,
  BoundingSphere,
  EasingFunction,
} from 'cesium';

export interface CameraTarget {
  longitude: number;
  latitude: number;
  height: number;
  heading?: number;
  pitch?: number;
  duration?: number;
}

export class CameraController {
  private beforeFly: (() => void)[] = [];

  constructor(private viewer: Viewer) {}

  /** Run before every programmatic flight (e.g. release a target lock,
   *  whose camera frame would otherwise bend the flight). */
  onBeforeFly(hook: () => void): void {
    this.beforeFly.push(hook);
  }

  /** Fly to look AT the target. Its longitude/latitude is the subject placed
   *  at screen centre; height is the camera altitude to arrive at. The old
   *  behaviour put the camera at those coordinates, so with a 30° tilt a
   *  landmark sat under the camera, out of frame. */
  flyTo(target: CameraTarget): Promise<void> {
    for (const hook of this.beforeFly) hook();
    // Keep at least 10° of tilt so the orbit range stays finite.
    const pitchDeg = Math.min(-10, target.pitch ?? -35);
    const pitch = CesiumMath.toRadians(pitchDeg);
    const range = target.height / Math.sin(-pitch);
    return new Promise((resolve) => {
      this.viewer.camera.flyToBoundingSphere(
        new BoundingSphere(
          Cartesian3.fromDegrees(target.longitude, target.latitude, 0),
          0
        ),
        {
          offset: new HeadingPitchRange(
            CesiumMath.toRadians(target.heading ?? 0),
            pitch,
            range
          ),
          // Undefined lets Cesium scale the duration with distance: a hop
          // across town is quick, a trip across the globe is not rushed.
          duration: target.duration,
          easingFunction: EasingFunction.QUADRATIC_IN_OUT,
          complete: () => resolve(),
          cancel: () => resolve(),
        }
      );
    });
  }

  /** Fly so the point sits at screen centre, framed by orbit range rather
   *  than camera altitude. */
  flyToPoint(
    longitude: number,
    latitude: number,
    range = 800_000,
    pitch = -55,
    duration = 3
  ): Promise<void> {
    for (const hook of this.beforeFly) hook();
    return new Promise((resolve) => {
      this.viewer.camera.flyToBoundingSphere(
        new BoundingSphere(Cartesian3.fromDegrees(longitude, latitude, 0), 0),
        {
          offset: new HeadingPitchRange(0, CesiumMath.toRadians(pitch), range),
          duration,
          complete: () => resolve(),
          cancel: () => resolve(),
        }
      );
    });
  }

  getCurrentPosition(): { longitude: number; latitude: number; height: number } {
    const carto = this.viewer.camera.positionCartographic;
    return {
      longitude: CesiumMath.toDegrees(carto.longitude),
      latitude: CesiumMath.toDegrees(carto.latitude),
      height: carto.height,
    };
  }
}
