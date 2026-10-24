import { Viewer } from "cesium";
import { SatelliteLayer } from "./satellites/satellite-layer";
import { FlightLayer } from "./flights/flight-layer";
import { MilitaryLayer } from "./flights/military-layer";
import { EarthquakeLayer } from "./earthquakes/earthquake-layer";
import { WeatherLayer } from "./weather/weather-layer";
import { CCTVLayer } from "./cctv/cctv-layer";
import { TrafficLayer } from "./traffic/traffic-layer";
import { WigleLayer } from "./wigle/wigle-layer";
import { FIRMSLayer } from "./firms/firms-layer";
import { ACLEDLayer } from "./acled/acled-layer";
import { ThreatLayer } from "./threats/threat-layer";
import { MaritimeLayer } from "./maritime/maritime-layer";
import { BorderLayer } from "./borders/border-layer";

export interface LayerStatus {
  name: string;
  visible: boolean;
  count: number;
}

export type LayerName =
  | "satellites"
  | "flights"
  | "military"
  | "earthquakes"
  | "weather"
  | "cctv"
  | "traffic"
  | "wigle"
  | "firms"
  | "acled"
  | "threats"
  | "maritime"
  | "borders";

export const LAYER_NAMES: LayerName[] = [
  "satellites", "flights", "military", "earthquakes", "weather", "cctv",
  "traffic", "wigle", "firms", "acled", "threats", "maritime",
  "borders",
];

/** Layers on at startup. Everything else stays unloaded (no fetches, no
 *  entities, no timers) until it is first switched on. */
const DEFAULT_ON: LayerName[] = ["threats", "borders", "satellites", "weather"];

export class LayerManager {
  public satellites: SatelliteLayer;
  public flights: FlightLayer;
  public military: MilitaryLayer;
  public earthquakes: EarthquakeLayer;
  public weather: WeatherLayer;
  public cctv: CCTVLayer;
  public traffic: TrafficLayer;
  public wigle: WigleLayer;
  public firms: FIRMSLayer;
  public acled: ACLEDLayer;
  public threats: ThreatLayer;
  public maritime: MaritimeLayer;
  public borders: BorderLayer;

  constructor(viewer: Viewer) {
    this.satellites = new SatelliteLayer(viewer);
    this.flights = new FlightLayer(viewer);
    this.military = new MilitaryLayer(viewer);
    this.earthquakes = new EarthquakeLayer(viewer);
    this.weather = new WeatherLayer(viewer);
    this.cctv = new CCTVLayer(viewer);
    this.traffic = new TrafficLayer(viewer);
    this.wigle = new WigleLayer(viewer);
    this.firms = new FIRMSLayer(viewer);
    this.acled = new ACLEDLayer(viewer);
    this.threats = new ThreatLayer(viewer);
    this.maritime = new MaritimeLayer(viewer);
    this.borders = new BorderLayer(viewer);

    // Lazy loading hooks every layer's own setVisible, so all the existing
    // toggle paths (keys, panels, presets, dock, share links) trigger the
    // first load without each being rewired. Hiding before load is safe:
    // each setVisible only walks its (still empty) entity collections.
    for (const name of LAYER_NAMES) {
      const layer = this[name] as { setVisible(v: boolean): void };
      const setVisible = layer.setVisible.bind(layer);
      layer.setVisible = (visible: boolean) => {
        setVisible(visible);
        if (visible) this.ensureLoaded(name);
      };
      if (!DEFAULT_ON.includes(name)) setVisible(false);
    }
  }

  private loading = new Map<LayerName, Promise<void>>();

  /** Load a layer once, the first time it is needed. */
  ensureLoaded(name: LayerName): Promise<void> {
    let p = this.loading.get(name);
    if (!p) {
      const layer = this[name] as { load?: () => Promise<void>; start?: () => Promise<void> };
      const run = layer.load ?? layer.start;
      p = (run ? run.call(layer) : Promise.resolve()).catch((e) => {
        console.warn(`Layer ${name} load failed:`, e);
      });
      this.loading.set(name, p);
    }
    return p;
  }

  isLoaded(name: LayerName): boolean {
    return this.loading.has(name);
  }

  /** Start loading the visible layers. Resolves once the threat layer is
   *  ready (deep links and share links target threats); the others finish
   *  in the background instead of holding up the first frame. */
  async loadAll(): Promise<void> {
    for (const name of LAYER_NAMES) {
      if (this[name].visible) this.ensureLoaded(name);
    }
    await this.loading.get("threats");
  }

  toggleLayer(name: LayerName): void {
    const layer = this[name];
    layer.setVisible(!layer.visible);
  }

  getStatus(): LayerStatus[] {
    return [
      { name: "Satellites",  visible: this.satellites.visible,  count: this.satellites.count },
      { name: "Flights",     visible: this.flights.visible,     count: this.flights.count },
      { name: "Military",    visible: this.military.visible,    count: this.military.count },
      { name: "Earthquakes", visible: this.earthquakes.visible, count: this.earthquakes.count },
      { name: "Weather",     visible: this.weather.visible,     count: this.weather.count },
      { name: "CCTV",        visible: this.cctv.visible,        count: this.cctv.count },
      { name: "Traffic",     visible: this.traffic.visible,     count: this.traffic.count },
      { name: "WiGLE",       visible: this.wigle.visible,       count: this.wigle.count },
      { name: "FIRMS",       visible: this.firms.visible,       count: this.firms.count },
      { name: "ACLED",       visible: this.acled.visible,       count: this.acled.count },
      { name: "Threats",     visible: this.threats.visible,     count: this.threats.count },
      { name: "Maritime",  visible: this.maritime.visible,  count: this.maritime.count },
      { name: "Borders",   visible: this.borders.visible,   count: this.borders.count },
    ];
  }

  destroy(): void {
    this.satellites.destroy();
    this.flights.destroy();
    this.military.destroy();
    this.earthquakes.destroy();
    this.weather.destroy();
    this.cctv.destroy();
    this.traffic.destroy();
    this.wigle.destroy();
    this.firms.destroy();
    this.acled.destroy();
    this.threats.destroy();
    this.maritime.destroy();
    this.borders.destroy();
  }
}
