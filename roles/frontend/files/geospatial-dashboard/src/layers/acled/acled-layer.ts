import {
  Viewer,
  Entity,
  Cartesian3,
  Color,
  NearFarScalar,
  DistanceDisplayCondition,
  VerticalOrigin,
  HorizontalOrigin,
} from "cesium";

function conflictSvg(hexColor: string): string {
  return `data:image/svg+xml,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="32" height="32">
    <circle cx="16" cy="16" r="5" fill="${hexColor}" opacity="0.85" stroke="#000" stroke-width="0.7"/>
    <line x1="16" y1="4" x2="16" y2="10" stroke="${hexColor}" stroke-width="1.5" opacity="0.7"/>
    <line x1="16" y1="22" x2="16" y2="28" stroke="${hexColor}" stroke-width="1.5" opacity="0.7"/>
    <line x1="4" y1="16" x2="10" y2="16" stroke="${hexColor}" stroke-width="1.5" opacity="0.7"/>
    <line x1="22" y1="16" x2="28" y2="16" stroke="${hexColor}" stroke-width="1.5" opacity="0.7"/>
  </svg>`)}`;
}
import {
  fetchConflictEvents,
  ConflictEvent,
  ACLED_EVENT_COLORS,
} from "./acled-api";

export class ACLEDLayer {
  private entities: Entity[] = [];
  private _visible = true;
  private loaded = false;
  private refreshInterval: number | null = null;

  constructor(private viewer: Viewer) {
    const toRemove: Entity[] = [];
    for (let i = 0; i < viewer.entities.values.length; i++) {
      const e = viewer.entities.values[i] as any;
      try {
        if (e.properties?.type?.getValue() === "acled") toRemove.push(e);
      } catch (_) {}
    }
    for (const e of toRemove) viewer.entities.remove(e);
  }

  async load(): Promise<void> {
    this.loaded = true;
    await this.fetchAndRender();
    // Auto-refresh every 30 minutes
    this.refreshInterval = window.setInterval(
      () => this.fetchAndRender(),
      1800000
    );
  }

  private async fetchAndRender(): Promise<void> {
    if (!this._visible) return;

    try {
      const events = await fetchConflictEvents();
      this.clearEntities();

      for (const evt of events) {
        if (!evt.latitude || !evt.longitude) continue;

        const colorHex =
          ACLED_EVENT_COLORS[evt.event_type] || "#33ff33";
        const color = Color.fromCssColorString(colorHex);
        const size = Math.max(
          4,
          Math.min(18, 4 + Math.sqrt(evt.fatalities) * 3)
        );

        const entity = this.viewer.entities.add({
          name: evt.event_type + " - " + evt.location,
          position: Cartesian3.fromDegrees(evt.longitude, evt.latitude, 50),
          billboard: {
            image: conflictSvg(color.toCssColorString()),
            width: size * 3,
            height: size * 3,
            verticalOrigin: VerticalOrigin.CENTER,
            horizontalOrigin: HorizontalOrigin.CENTER,
            scaleByDistance: new NearFarScalar(1e5, 1.5, 5e7, 0.3),
            distanceDisplayCondition: new DistanceDisplayCondition(0, 5e7),
          },
          label: {
            text: evt.event_type,
            font: "9px monospace",
            fillColor: color,
            showBackground: true,
            backgroundColor: Color.fromAlpha(Color.BLACK, 0.7),
            pixelOffset: new Cartesian3(0, -14, 0) as any,
            scaleByDistance: new NearFarScalar(1e5, 1, 5e6, 0.2),
            distanceDisplayCondition: new DistanceDisplayCondition(0, 5e6),
          },
          show: this._visible,
          properties: {
            type: "acled",
            eventType: evt.event_type,
            subEventType: evt.sub_event_type,
            actor1: evt.actor1,
            actor2: evt.actor2,
            fatalities: evt.fatalities,
            eventDate: evt.event_date,
            country: evt.country,
            location: evt.location,
            notes: evt.notes,
          } as any,
        });

        this.entities.push(entity);
      }

      if (events.length > 0) {
        this.viewer.scene.requestRender();
        console.log("Loaded " + events.length + " ACLED conflict events");
      }
    } catch (e) {
      console.warn("ACLED load failed:", e);
    }
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
    if (!visible) this.clearEntities();
    this.viewer.scene.requestRender();
  }

  get visible(): boolean {
    return this._visible;
  }

  get count(): number {
    return this.entities.length;
  }

  destroy(): void {
    if (this.refreshInterval !== null) clearInterval(this.refreshInterval);
    this.clearEntities();
  }
}
