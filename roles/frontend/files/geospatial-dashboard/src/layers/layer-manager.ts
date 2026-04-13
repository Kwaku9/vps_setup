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
import { ArtemisLayer } from "./artemis/artemis-layer";

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
  | "artemis";

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
  public artemis: ArtemisLayer;

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
    this.artemis = new ArtemisLayer(viewer);
  }

  async loadAll(): Promise<void> {
    const results = await Promise.allSettled([
      this.satellites.load(),
      this.flights.start(),
      this.military.start(),
      this.earthquakes.load(),
      this.weather.load(),
      this.cctv.load(),
      this.traffic.load(),
      this.wigle.load(),
      this.firms.load(),
      this.acled.load(),
      this.threats.load(),
      this.maritime.start(),
      this.artemis.load(),
    ]);

    for (const result of results) {
      if (result.status === "rejected") {
        console.warn("Layer load failed:", result.reason);
      }
    }
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
      { name: "Artemis",   visible: this.artemis.visible,   count: this.artemis.count },
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
    this.artemis.destroy();
  }
}
