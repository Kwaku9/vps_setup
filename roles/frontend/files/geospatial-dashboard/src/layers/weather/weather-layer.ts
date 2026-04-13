import {
  Viewer,
  Entity,
  Cartesian3,
  Rectangle,
  Color,
  Math as CesiumMath,
  ImageMaterialProperty,
} from "cesium";

interface RainViewerFrame {
  time: number;
  path: string;
}

const TILE_SIZE = 256;
const TILE_HOST = "https://tilecache.rainviewer.com";
// Color scheme: 2 = original, 4 = dark sky, 6 = NEXRAD
const COLOR_SCHEME = 4;
// Smooth rendering
const SMOOTH = 1;
// Opacity in tile URL (0-100 %)
const TILE_OPACITY = 70;

/**
 * Weather radar layer using RainViewer API (free, global, no auth).
 * Works without a Cesium globe by rendering radar tiles as Entity rectangles.
 */
export class WeatherLayer {
  private entities: Entity[] = [];
  private _visible = true;
  private _available = false;
  private latestPath = "";
  private pollTimer: number | null = null;

  constructor(private viewer: Viewer) {}

  async load(): Promise<void> {
    try {
      await this.fetchAndRender();
      this._available = true;
      // Refresh radar every 5 minutes
      this.pollTimer = window.setInterval(() => this.fetchAndRender(), 300000);
      console.log("Weather radar loaded (RainViewer global)");
    } catch (e) {
      console.warn("Weather radar unavailable:", e);
    }
  }

  private async fetchAndRender(): Promise<void> {
    const resp = await fetch("https://api.rainviewer.com/public/weather-maps.json");
    if (!resp.ok) throw new Error("RainViewer API " + resp.status);

    const data = await resp.json();
    const frames: RainViewerFrame[] = data.radar?.past || [];
    if (frames.length === 0) return;

    const latest = frames[frames.length - 1];

    // Skip if same frame
    if (latest.path === this.latestPath) return;
    this.latestPath = latest.path;

    // Clear old tiles
    this.clearEntities();

    // Get camera position to determine which tiles to load
    const cam = this.viewer.camera.positionCartographic;
    const camLat = CesiumMath.toDegrees(cam.latitude);
    const camLon = CesiumMath.toDegrees(cam.longitude);
    const camAlt = cam.height;

    // Choose zoom level based on camera altitude
    let zoom: number;
    if (camAlt > 8000000) zoom = 1;
    else if (camAlt > 4000000) zoom = 2;
    else if (camAlt > 1500000) zoom = 3;
    else if (camAlt > 500000) zoom = 4;
    else if (camAlt > 100000) zoom = 5;
    else zoom = 6;

    // Calculate which tiles cover the viewport
    const tiles = getTilesForView(camLat, camLon, zoom, camAlt);

    for (const tile of tiles) {
      const url = `${TILE_HOST}${latest.path}/${TILE_SIZE}/${zoom}/${tile.x}/${tile.y}/${COLOR_SCHEME}/${SMOOTH}_${TILE_OPACITY}.png`;
      const bounds = tileBounds(tile.x, tile.y, zoom);

      const entity = this.viewer.entities.add({
        rectangle: {
          coordinates: Rectangle.fromDegrees(
            bounds.west,
            bounds.south,
            bounds.east,
            bounds.north
          ),
          material: new ImageMaterialProperty({
            image: url,
            transparent: true,
          }),
          height: 500,
          classificationType: undefined,
        },
        show: this._visible,
        properties: {
          type: "weather-tile",
        } as any,
      });

      this.entities.push(entity);
    }

    this.viewer.scene.requestRender();
  }

  private clearEntities(): void {
    for (const e of this.entities) {
      this.viewer.entities.remove(e);
    }
    this.entities = [];
  }

  setVisible(visible: boolean): void {
    this._visible = visible;
    for (const e of this.entities) {
      e.show = visible;
    }
    this.viewer.scene.requestRender();
  }

  get visible(): boolean {
    return this._visible;
  }

  get count(): number {
    return this._available ? 1 : 0;
  }

  destroy(): void {
    if (this.pollTimer !== null) {
      clearInterval(this.pollTimer);
    }
    this.clearEntities();
  }
}

// ── Slippy tile math ─────────────────────────────────────

function lon2tile(lon: number, zoom: number): number {
  return Math.floor(((lon + 180) / 360) * Math.pow(2, zoom));
}

function lat2tile(lat: number, zoom: number): number {
  const latRad = (lat * Math.PI) / 180;
  return Math.floor(
    ((1 - Math.log(Math.tan(latRad) + 1 / Math.cos(latRad)) / Math.PI) / 2) *
      Math.pow(2, zoom)
  );
}

function tileBounds(
  x: number,
  y: number,
  zoom: number
): { north: number; south: number; east: number; west: number } {
  const n = Math.pow(2, zoom);
  const west = (x / n) * 360 - 180;
  const east = ((x + 1) / n) * 360 - 180;
  const north =
    (Math.atan(Math.sinh(Math.PI * (1 - (2 * y) / n))) * 180) / Math.PI;
  const south =
    (Math.atan(Math.sinh(Math.PI * (1 - (2 * (y + 1)) / n))) * 180) / Math.PI;
  return { north, south, east, west };
}

function getTilesForView(
  lat: number,
  lon: number,
  zoom: number,
  altitude: number
): { x: number; y: number }[] {
  const centerX = lon2tile(lon, zoom);
  const centerY = lat2tile(lat, zoom);

  // How many tiles to load around center (based on altitude)
  let radius: number;
  if (altitude > 8000000) radius = 1;
  else if (altitude > 3000000) radius = 2;
  else if (altitude > 500000) radius = 3;
  else radius = 4;

  const maxTile = Math.pow(2, zoom) - 1;
  const tiles: { x: number; y: number }[] = [];

  for (let dx = -radius; dx <= radius; dx++) {
    for (let dy = -radius; dy <= radius; dy++) {
      const x = centerX + dx;
      const y = centerY + dy;
      if (x >= 0 && x <= maxTile && y >= 0 && y <= maxTile) {
        tiles.push({ x, y });
      }
    }
  }

  return tiles;
}
