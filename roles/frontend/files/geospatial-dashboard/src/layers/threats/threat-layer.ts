// Live Threat Attack Map Layer
// Renders CrowdSec decisions as animated missile arcs from attacker origin to VPS

import {
  Viewer,
  Entity,
  Cartesian3,
  Color,
  CallbackProperty,
  NearFarScalar,
  DistanceDisplayCondition,
  PolylineGlowMaterialProperty,
  JulianDate,
  SampledPositionProperty,
  LagrangePolynomialApproximation,
} from "cesium";
import {
  ThreatEvent,
  fetchThreatEvents,
  SCENARIO_COLORS,
  DEFAULT_THREAT_COLOR,
  getScenarioLabel,
} from "./crowdsec-api";

const MAX_THREATS = 200;
const POLL_INTERVAL = 30_000;
const ARC_SEGMENTS = 48;
const ARC_MAX_HEIGHT = 400_000;
const MAX_AGE_MS = 86_400_000;      // 24 hours

// Missile timing
const MISSILE_MIN_DELAY = 500;    // 0.5s minimum between launches
const MISSILE_MAX_DELAY = 2000;   // 2s maximum between launches
const MISSILE_MIN_TRAVEL = 2500;  // 2.5s minimum flight time
const MISSILE_MAX_TRAVEL = 5000;  // 5s maximum flight time
const IMPACT_FLASH_MS = 600;      // flash duration at VPS on impact
const MAX_CONCURRENT_MISSILES = 5;

const VPS_LAT = parseFloat(import.meta.env.VITE_VPS_LAT || "0");
const VPS_LON = parseFloat(import.meta.env.VITE_VPS_LON || "0");

interface ThreatEntityGroup {
  source: Entity;
  arc: Entity;
  arcPositions: Cartesian3[];
  event: ThreatEvent;
  createdAt: number;
}

interface ActiveMissile {
  entity: Entity;
  trailEntity: Entity | null;
  removeTimer: number;
}

function greatCircleArc(
  srcLat: number, srcLon: number,
  dstLat: number, dstLon: number,
  segments: number
): Cartesian3[] {
  const toRad = Math.PI / 180;
  const lat1 = srcLat * toRad;
  const lon1 = srcLon * toRad;
  const lat2 = dstLat * toRad;
  const lon2 = dstLon * toRad;

  const d = 2 * Math.asin(Math.sqrt(
    Math.sin((lat2 - lat1) / 2) ** 2 +
    Math.cos(lat1) * Math.cos(lat2) * Math.sin((lon2 - lon1) / 2) ** 2
  ));

  const positions: Cartesian3[] = [];
  for (let i = 0; i <= segments; i++) {
    const f = i / segments;
    const A = Math.sin((1 - f) * d) / Math.sin(d) || 1 - f;
    const B = Math.sin(f * d) / Math.sin(d) || f;

    const x = A * Math.cos(lat1) * Math.cos(lon1) + B * Math.cos(lat2) * Math.cos(lon2);
    const y = A * Math.cos(lat1) * Math.sin(lon1) + B * Math.cos(lat2) * Math.sin(lon2);
    const z = A * Math.sin(lat1) + B * Math.sin(lat2);

    const lat = Math.atan2(z, Math.sqrt(x * x + y * y));
    const lon = Math.atan2(y, x);
    const height = Math.sin(f * Math.PI) * ARC_MAX_HEIGHT;

    positions.push(Cartesian3.fromDegrees(lon / toRad, lat / toRad, height));
  }
  return positions;
}

function randomBetween(min: number, max: number): number {
  return min + Math.random() * (max - min);
}

export class ThreatLayer {
  private groups: ThreatEntityGroup[] = [];
  private missiles: ActiveMissile[] = [];
  private vpsMarker: Entity | null = null;
  private impactFlash: Entity | null = null;
  private _visible = true;
  private pollTimer: number | null = null;
  private lastPollTime = 0;
  private pulsePhase = 0;
  private pulseTimer: number | null = null;

  // Missile launcher state
  private launchTimer: number | null = null;
  private launchIndex = 0;
  private impactFlashTimer: number | null = null;

  private countryFilter: string | null = null;

  constructor(private viewer: Viewer) {
    const toRemove: Entity[] = [];
    for (let i = 0; i < viewer.entities.values.length; i++) {
      const e = viewer.entities.values[i] as any;
      try {
        if (e.properties?.type?.getValue() === "threat") toRemove.push(e);
      } catch (_) {}
    }
    for (const e of toRemove) viewer.entities.remove(e);
  }

  /** Filter threat arcs to a specific ISO-3166 country code (e.g. "CN").
   *  Pass null to show all threats. */
  setCountryFilter(country: string | null): void {
    this.countryFilter = country ? country.toUpperCase() : null;
    for (const g of this.groups) {
      const match = !this.countryFilter ||
        g.event.country?.toUpperCase() === this.countryFilter;
      g.source.show = this._visible && match;
      g.arc.show = this._visible && match;
    }
    this.viewer.scene.requestRender();
  }

  get countryFilterActive(): string | null {
    return this.countryFilter;
  }

  async load(): Promise<void> {
    if (!VPS_LAT && !VPS_LON) {
      console.warn("Threats: Set VITE_VPS_LAT/VITE_VPS_LON in .env");
      return;
    }

    this.createVPSMarker();
    this.createImpactFlash();

    try {
      const events = await fetchThreatEvents("-24h");
      for (const evt of events) {
        this.addThreat(evt);
      }
      this.viewer.scene.requestRender();
      console.log(`Threats: loaded ${events.length} events`);
    } catch (e) {
      console.warn("Threats: initial load failed:", e);
    }

    // Start polling
    this.lastPollTime = Date.now();
    this.pollTimer = window.setInterval(() => this.poll(), POLL_INTERVAL);

    // Pulse animation
    this.pulseTimer = window.setInterval(() => {
      this.pulsePhase += 0.15;
      this.pruneOld();
    }, 100);

    // Start missile launcher — fires continuously
    this.scheduleLaunch();
  }

  private createVPSMarker(): void {
    const self = this;
    this.vpsMarker = this.viewer.entities.add({
      name: "VPS TARGET",
      position: Cartesian3.fromDegrees(VPS_LON, VPS_LAT, 1000),
      point: {
        pixelSize: new CallbackProperty(
          () => 6 + 2 * Math.sin(self.pulsePhase * 2),
          false
        ) as any,
        color: Color.WHITE.withAlpha(0.9),
        outlineColor: Color.CYAN,
        outlineWidth: 2,
        scaleByDistance: new NearFarScalar(1e5, 2.0, 5e7, 0.5),
        distanceDisplayCondition: new DistanceDisplayCondition(0, 5e7),
      },
      show: this._visible,
    });
  }

  private createImpactFlash(): void {
    // Hidden by default, shown briefly on missile impact
    this.impactFlash = this.viewer.entities.add({
      position: Cartesian3.fromDegrees(VPS_LON, VPS_LAT, 2000),
      point: {
        pixelSize: 30,
        color: Color.WHITE.withAlpha(0.9),
        outlineColor: Color.RED.withAlpha(0.7),
        outlineWidth: 4,
        scaleByDistance: new NearFarScalar(1e5, 2.0, 5e7, 0.5),
        distanceDisplayCondition: new DistanceDisplayCondition(0, 5e7),
      },
      show: false,
    });
  }

  private triggerImpact(color: Color): void {
    if (!this.impactFlash) return;

    // Flash the impact marker
    this.impactFlash.show = this._visible;
    if (this.impactFlash.point) {
      (this.impactFlash.point.color as any).setValue(Color.WHITE.withAlpha(0.95));
      (this.impactFlash.point.outlineColor as any).setValue(color.withAlpha(0.8));
    }
    this.viewer.scene.requestRender();

    // Fade out after IMPACT_FLASH_MS
    if (this.impactFlashTimer !== null) clearTimeout(this.impactFlashTimer);
    this.impactFlashTimer = window.setTimeout(() => {
      if (this.impactFlash) this.impactFlash.show = false;
      this.viewer.scene.requestRender();
    }, IMPACT_FLASH_MS);
  }

  private scheduleLaunch(): void {
    if (this.launchTimer !== null) clearTimeout(this.launchTimer);
    const delay = randomBetween(MISSILE_MIN_DELAY, MISSILE_MAX_DELAY);
    this.launchTimer = window.setTimeout(() => {
      this.launchNextMissile();
      this.scheduleLaunch();
    }, delay);
  }

  private launchNextMissile(): void {
    if (!this._visible || this.groups.length === 0) return;
    if (this.missiles.length >= MAX_CONCURRENT_MISSILES) return;

    // Respect country filter — only launch from visible groups
    const launchable = this.countryFilter
      ? this.groups.filter(
          (g) => g.event.country?.toUpperCase() === this.countryFilter
        )
      : this.groups;
    if (launchable.length === 0) return;

    // Cycle through threats round-robin
    this.launchIndex = this.launchIndex % launchable.length;
    const group = launchable[this.launchIndex];
    this.launchIndex++;

    const colorHex = SCENARIO_COLORS[group.event.scenario] || DEFAULT_THREAT_COLOR;
    const color = Color.fromCssColorString(colorHex);

    // Travel time varies by distance (longer arcs = longer travel)
    const arcLen = group.arcPositions.length;
    const travelMs = MISSILE_MIN_TRAVEL +
      (arcLen / ARC_SEGMENTS) * (MISSILE_MAX_TRAVEL - MISSILE_MIN_TRAVEL);

    this.fireMissile(group.arcPositions, color, travelMs);
  }

  private fireMissile(
    arcPositions: Cartesian3[],
    color: Color,
    travelMs: number
  ): void {
    const now = JulianDate.now();
    const positionProperty = new SampledPositionProperty();
    positionProperty.setInterpolationOptions({
      interpolationDegree: 3,
      interpolationAlgorithm: LagrangePolynomialApproximation,
    });

    const steps = 24;
    const stepIndex = Math.max(1, Math.floor(arcPositions.length / steps));
    for (let i = 0; i <= steps; i++) {
      const idx = Math.min(i * stepIndex, arcPositions.length - 1);
      const t = JulianDate.addSeconds(
        now,
        (i / steps) * (travelMs / 1000),
        new JulianDate()
      );
      positionProperty.addSample(t, arcPositions[idx]);
    }

    // Missile head — bright glowing dot
    const missile = this.viewer.entities.add({
      position: positionProperty,
      point: {
        pixelSize: 8,
        color: Color.WHITE,
        outlineColor: color,
        outlineWidth: 3,
        scaleByDistance: new NearFarScalar(1e5, 2.5, 5e7, 0.6),
        distanceDisplayCondition: new DistanceDisplayCondition(0, 5e7),
      },
      show: this._visible,
    });

    // Missile trail — fading tail behind the head
    const trailLength = Math.min(12, Math.floor(arcPositions.length * 0.25));
    let trailEntity: Entity | null = null;

    // Animated trail using CallbackProperty
    let trailProgress = 0;
    const trailStartTime = Date.now();

    trailEntity = this.viewer.entities.add({
      polyline: {
        positions: new CallbackProperty(() => {
          const elapsed = Date.now() - trailStartTime;
          trailProgress = Math.min(1, elapsed / travelMs);
          const headIdx = Math.floor(trailProgress * (arcPositions.length - 1));
          const tailIdx = Math.max(0, headIdx - trailLength);
          return arcPositions.slice(tailIdx, headIdx + 1);
        }, false) as any,
        width: 3,
        material: new PolylineGlowMaterialProperty({
          glowPower: 0.4,
          color: color.withAlpha(0.8),
        }),
        distanceDisplayCondition: new DistanceDisplayCondition(0, 5e7),
      },
      show: this._visible,
    });

    // Remove missile + trail after arrival, trigger impact flash
    const removeTimer = window.setTimeout(() => {
      this.triggerImpact(color);
      this.viewer.entities.remove(missile);
      if (trailEntity) this.viewer.entities.remove(trailEntity);
      this.missiles = this.missiles.filter((m) => m.entity !== missile);
      this.viewer.scene.requestRender();
    }, travelMs);

    this.missiles.push({ entity: missile, trailEntity, removeTimer });
  }

  private async poll(): Promise<void> {
    if (!this._visible) return;
    try {
      const events = await fetchThreatEvents("-60s");
      const now = Date.now();
      for (const evt of events) {
        if (evt.timestamp > this.lastPollTime - 60_000) {
          const exists = this.groups.some(
            (g) =>
              g.event.ip === evt.ip &&
              g.event.scenario === evt.scenario &&
              Math.abs(g.event.timestamp - evt.timestamp) < 60_000
          );
          if (!exists) {
            this.addThreat(evt);
          }
        }
      }
      this.lastPollTime = now;
    } catch {
      // silent retry
    }
  }

  private addThreat(event: ThreatEvent): void {
    while (this.groups.length >= MAX_THREATS) {
      const oldest = this.groups.shift();
      if (oldest) {
        this.viewer.entities.remove(oldest.source);
        this.viewer.entities.remove(oldest.arc);
      }
    }

    const colorHex = SCENARIO_COLORS[event.scenario] || DEFAULT_THREAT_COLOR;
    const color = Color.fromCssColorString(colorHex);
    const label = getScenarioLabel(event.scenario);
    const self = this;

    // Source dot (pulsing)
    const source = this.viewer.entities.add({
      name: `${label} — ${event.ip}`,
      position: Cartesian3.fromDegrees(event.longitude, event.latitude, 500),
      point: {
        pixelSize: new CallbackProperty(
          () => 5 + 2 * Math.sin(self.pulsePhase + event.latitude),
          false
        ) as any,
        color: color.withAlpha(0.6),
        outlineColor: color,
        outlineWidth: 1,
        scaleByDistance: new NearFarScalar(1e5, 2.0, 5e7, 0.4),
        distanceDisplayCondition: new DistanceDisplayCondition(0, 5e7),
      },
      label: {
        text: event.country || event.ip,
        font: "9px monospace",
        fillColor: color.withAlpha(0.6),
        showBackground: true,
        backgroundColor: Color.BLACK.withAlpha(0.6),
        pixelOffset: new Cartesian3(0, -14, 0) as any,
        scaleByDistance: new NearFarScalar(1e5, 1, 5e6, 0.2),
        distanceDisplayCondition: new DistanceDisplayCondition(0, 5e6),
      },
      show: this._visible,
      properties: {
        type: "threat",
        ip: event.ip,
        country: event.country,
        scenario: event.scenario,
        scenarioLabel: label,
        severity: "",
        asname: event.asname,
        asnumber: event.asnumber,
        iprange: event.iprange,
        duration: event.duration,
        decisionType: event.type,
        timestamp: event.timestamp,
      } as any,
    });

    // Static arc — faint background trace
    const arcPositions = greatCircleArc(
      event.latitude, event.longitude,
      VPS_LAT, VPS_LON,
      ARC_SEGMENTS
    );

    const arc = this.viewer.entities.add({
      polyline: {
        positions: arcPositions,
        width: 1,
        material: new PolylineGlowMaterialProperty({
          glowPower: 0.15,
          color: color.withAlpha(0.15),
        }),
        distanceDisplayCondition: new DistanceDisplayCondition(0, 5e7),
      },
      show: this._visible,
    });

    // Apply country filter to newly added threat
    if (this.countryFilter && event.country?.toUpperCase() !== this.countryFilter) {
      source.show = false;
      arc.show = false;
    }

    this.groups.push({ source, arc, arcPositions, event, createdAt: Date.now() });
  }

  private pruneOld(): void {
    const now = Date.now();
    const expired = this.groups.filter(
      (g) => now - g.event.timestamp > MAX_AGE_MS
    );
    for (const g of expired) {
      this.viewer.entities.remove(g.source);
      this.viewer.entities.remove(g.arc);
    }
    if (expired.length) {
      this.groups = this.groups.filter(
        (g) => now - g.event.timestamp <= MAX_AGE_MS
      );
      this.viewer.scene.requestRender();
    }
  }

  setVisible(visible: boolean): void {
    this._visible = visible;
    for (const g of this.groups) {
      g.source.show = visible;
      g.arc.show = visible;
    }
    for (const m of this.missiles) {
      m.entity.show = visible;
      if (m.trailEntity) m.trailEntity.show = visible;
    }
    if (this.vpsMarker) this.vpsMarker.show = visible;
    if (this.impactFlash && !visible) this.impactFlash.show = false;
    this.viewer.scene.requestRender();
  }

  get visible(): boolean {
    return this._visible;
  }

  get count(): number {
    return this.groups.length;
  }

getLatestForCountry(country: string): { latitude: number; longitude: number; ip: string; scenario: string } | null {    const upper = country.toUpperCase();    let latest: ThreatEntityGroup | null = null;    for (const g of this.groups) {      if (g.event.country?.toUpperCase() !== upper) continue;      if (!latest || g.event.timestamp > latest.event.timestamp) latest = g;    }    if (!latest) return null;    return {      latitude: latest.event.latitude,      longitude: latest.event.longitude,      ip: latest.event.ip,      scenario: latest.event.scenario,    };  }
  destroy(): void {
    if (this.pollTimer !== null) clearInterval(this.pollTimer);
    if (this.pulseTimer !== null) clearInterval(this.pulseTimer);
    if (this.launchTimer !== null) clearTimeout(this.launchTimer);
    if (this.impactFlashTimer !== null) clearTimeout(this.impactFlashTimer);
    for (const m of this.missiles) {
      clearTimeout(m.removeTimer);
      this.viewer.entities.remove(m.entity);
      if (m.trailEntity) this.viewer.entities.remove(m.trailEntity);
    }
    for (const g of this.groups) {
      this.viewer.entities.remove(g.source);
      this.viewer.entities.remove(g.arc);
    }
    if (this.vpsMarker) this.viewer.entities.remove(this.vpsMarker);
    if (this.impactFlash) this.viewer.entities.remove(this.impactFlash);
    this.groups = [];
    this.missiles = [];
  }
}
