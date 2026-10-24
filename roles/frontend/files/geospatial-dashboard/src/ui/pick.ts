import { Viewer, Cartesian2, Entity, JulianDate } from "cesium";

/** Threat entity under a screen position, or null.
 *  scene.pick() returns only the top primitive, and with photorealistic 3D
 *  tiles that is usually the terrain mesh, not the few-pixel threat dot
 *  floating over it. drillPick looks through the stack, with a padded window
 *  so the small pulsing dots are reachable. */
export function pickThreat(viewer: Viewer, position: Cartesian2): Entity | null {
  const time: JulianDate = viewer.clock.currentTime;
  const hits = viewer.scene.drillPick(position, 6, 20, 20);
  for (const hit of hits) {
    const entity = hit?.id;
    if (
      entity instanceof Entity &&
      entity.properties?.type?.getValue(time) === "threat"
    ) {
      return entity;
    }
  }
  return null;
}
