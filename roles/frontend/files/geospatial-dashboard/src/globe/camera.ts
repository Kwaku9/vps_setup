import {
  Viewer,
  Cartesian3,
  Math as CesiumMath,
  HeadingPitchRange,
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
  constructor(private viewer: Viewer) {}

  flyTo(target: CameraTarget): Promise<void> {
    return new Promise((resolve) => {
      this.viewer.camera.flyTo({
        destination: Cartesian3.fromDegrees(
          target.longitude,
          target.latitude,
          target.height
        ),
        orientation: {
          heading: CesiumMath.toRadians(target.heading ?? 0),
          pitch: CesiumMath.toRadians(target.pitch ?? -35),
          roll: 0,
        },
        duration: target.duration ?? 3,
        complete: () => resolve(),
        cancel: () => resolve(),
      });
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
