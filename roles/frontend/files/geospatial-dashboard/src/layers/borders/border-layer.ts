import {
  Viewer,
  GeoJsonDataSource,
  Color,
  ColorMaterialProperty,
  ConstantProperty,
  DistanceDisplayCondition,
  Cartographic,
  Cartesian3,
} from "cesium";

// Country borders — Natural Earth 110m admin-0 land boundaries (public/geo/).
// Styled as faint phosphor lines that only appear at strategic altitudes; the
// lines float ~12 km above the ellipsoid so they never sink into 3D terrain.
const BORDER_COLOR = Color.fromCssColorString("#00ff88").withAlpha(0.22);
const LINE_HEIGHT_M = 12_000;
const MIN_VISIBLE_DISTANCE_M = 350_000;   // hide when zoomed close (tiles win)

export class BorderLayer {
  public visible = true;
  public count = 0;
  private ds: GeoJsonDataSource | null = null;

  constructor(private viewer: Viewer) {}

  async load(): Promise<void> {
    this.ds = await GeoJsonDataSource.load("/geo/admin0-boundaries.geojson");

    const material = new ColorMaterialProperty(BORDER_COLOR);
    const ddc = new ConstantProperty(
      new DistanceDisplayCondition(MIN_VISIBLE_DISTANCE_M, Number.MAX_VALUE)
    );

    for (const entity of this.ds.entities.values) {
      const line = entity.polyline;
      if (!line) continue;
      line.material = material;
      line.width = new ConstantProperty(1);
      line.distanceDisplayCondition = ddc;

      // Lift each vertex so borders ride above terrain/buildings.
      const positions = line.positions?.getValue(this.viewer.clock.currentTime);
      if (positions) {
        const lifted = (positions as Cartesian3[]).map((p) => {
          const c = Cartographic.fromCartesian(p);
          c.height = LINE_HEIGHT_M;
          return Cartographic.toCartesian(c);
        });
        line.positions = new ConstantProperty(lifted);
      }
    }

    await this.viewer.dataSources.add(this.ds);
    this.count = this.ds.entities.values.length;
  }

  setVisible(v: boolean): void {
    this.visible = v;
    if (this.ds) this.ds.show = v;
  }

  destroy(): void {
    if (this.ds) {
      this.viewer.dataSources.remove(this.ds, true);
      this.ds = null;
    }
  }
}
