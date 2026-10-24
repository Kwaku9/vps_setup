import { Viewer, Entity, Cartesian3, Ellipsoid } from "cesium";

const R = Ellipsoid.WGS84.radii;

/** Ellipsoid horizon test (the one Cesium's internal EllipsoidalOccluder
 *  uses), in scaled space where the Earth is a unit sphere: a point is hidden
 *  when it lies beyond the horizon plane AND inside the horizon cone. */
function scaled(p: Cartesian3, out: Cartesian3): Cartesian3 {
  return Cartesian3.fromElements(p.x / R.x, p.y / R.y, p.z / R.z, out);
}
const sc = new Cartesian3();
const sp = new Cartesian3();
const vt = new Cartesian3();
function isPointVisible(cameraScaled: Cartesian3, point: Cartesian3): boolean {
  const vhMagSq = Cartesian3.magnitudeSquared(cameraScaled) - 1;
  if (vhMagSq < 0) return true; // camera inside the ellipsoid: no horizon
  Cartesian3.subtract(scaled(point, sp), cameraScaled, vt);
  const vtDotVc = -Cartesian3.dot(vt, cameraScaled);
  const occluded =
    vtDotVc > vhMagSq &&
    (vtDotVc * vtDotVc) / Cartesian3.magnitudeSquared(vt) > vhMagSq;
  return !occluded;
}

/**
 * Hide markers that are behind the Earth from the camera.
 *
 * The viewer runs with Cesium's globe off (the Earth is Google's 3D tiles),
 * so nothing occludes billboards past the horizon: distant tiles are barely
 * loaded, and markers have no solid surface to depth-test against. At an
 * oblique view, ships from a coast hundreds of kilometres away were drawn
 * over the Nevada desert, stacked near the horizon and sliding against the
 * terrain as the camera moved.
 *
 * This applies the ellipsoid horizon test to every billboard and point
 * entity, a few times a second while the camera moves. It drives the
 * billboard/point/label `show` flags, never `entity.show`, which belongs to
 * the layer toggles.
 */
export function installHorizonCulling(viewer: Viewer): void {
  const scratch = new Cartesian3();
  let pending = false;

  const cull = () => {
    pending = false;
    const cameraScaled = scaled(viewer.camera.positionWC, sc);
    const time = viewer.clock.currentTime;
    const entities = viewer.entities.values;
    for (let i = 0; i < entities.length; i++) {
      const e: Entity = entities[i];
      if (!e.billboard && !e.point) continue;
      const pos = e.position?.getValue(time, scratch);
      if (!pos) continue;
      const visible = isPointVisible(cameraScaled, pos);
      if (e.billboard) e.billboard.show = visible as any;
      if (e.point) e.point.show = visible as any;
      if (e.label) e.label.show = visible as any;
    }
    viewer.scene.requestRender();
  };

  const schedule = () => {
    if (pending) return;
    pending = true;
    window.setTimeout(cull, 150);
  };

  viewer.camera.changed.addEventListener(schedule);
  viewer.camera.moveEnd.addEventListener(schedule);
  // New markers arrive with every poll, and satellites move under a still
  // camera, so also sweep on a slow timer.
  window.setInterval(schedule, 1000);
  schedule();
}
