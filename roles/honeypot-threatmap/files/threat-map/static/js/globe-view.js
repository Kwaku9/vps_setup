// globe.gl wrapper: attack arcs, impact rings, VPS marker.
// Arc/ring hues use the bright glow variants (atmosphere layer, not chart
// marks); the timeline + chips carry the validated data tones and labels.
import { sourceMeta } from './util.js';

const ARCS_LIMIT = 80;
const LIVE_ARC_TTL = 8000;
const IP_ARC_COOLDOWN = 15000;   // one arc per IP+type per 15s (feed still counts)

const REDUCED_MOTION = window.matchMedia
  && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

export class GlobeView {
  constructor(container) {
    this.container = container;
    this.globe = null;
    this.arcs = [];
    this.rings = [];
    this.target = { lat: 40.7128, lng: -74.006 };
    this._cooldown = new Map();
    this._idleTimer = null;
    this._userHold = false;
  }

  init(target) {
    if (target) this.target = { lat: target.lat, lng: target.lon };
    const w = this.container.offsetWidth || window.innerWidth - 320;
    const h = this.container.offsetHeight || window.innerHeight - 150;

    this.globe = Globe()(this.container)
      .globeImageUrl('/static/vendor/earth-night.jpg')
      .bumpImageUrl('/static/vendor/earth-topology.png')
      .width(w)
      .height(h)
      .arcsData([])
      .arcStartLat((d) => d.startLat).arcStartLng((d) => d.startLng)
      .arcEndLat((d) => d.endLat).arcEndLng((d) => d.endLng)
      .arcColor((d) => d.color)
      .arcAltitudeAutoScale(0.32)
      .arcStroke((d) => d.stroke)
      .arcDashLength(0.45).arcDashGap(0.25)
      .arcDashAnimateTime(REDUCED_MOTION ? 0 : 1600)
      .ringsData([])
      .ringColor((d) => (t) => `rgba(${d.rgb},${Math.max(0, 1 - t)})`)
      .ringMaxRadius((d) => d.max)
      .ringPropagationSpeed(2.2)
      .ringRepeatPeriod(9999)     // one pulse per ring datum
      .pointsData([{ lat: this.target.lat, lng: this.target.lng }])
      .pointColor(() => '#00ff88')
      .pointAltitude(0.012)
      .pointRadius(0.45)
      .pointLabel(() => 'AICORTEX C2')
      .backgroundColor('rgba(0,0,0,0)');

    this.globe.controls().autoRotate = !REDUCED_MOTION;
    this.globe.controls().autoRotateSpeed = 0.35;
    this.globe.pointOfView({ lat: 22, lng: 10, altitude: 2.4 });

    const canvas = this.container.querySelector('canvas');
    if (canvas) canvas.style.background = 'transparent';

    // Pause auto-rotate while the user is dragging; resume after 15s idle.
    this.container.addEventListener('pointerdown', () => this._holdRotation());
    window.addEventListener('resize', () => {
      this.globe.width(this.container.offsetWidth)
        .height(this.container.offsetHeight);
    });
  }

  _holdRotation() {
    this._userHold = true;
    this.globe.controls().autoRotate = false;
    clearTimeout(this._idleTimer);
    this._idleTimer = setTimeout(() => {
      this._userHold = false;
      if (!REDUCED_MOTION) this.globe.controls().autoRotate = true;
    }, 15000);
  }

  setTarget(target) {
    this.target = { lat: target.lat, lng: target.lon };
    this.globe.pointsData([{ lat: this.target.lat, lng: this.target.lng }]);
  }

  // speed=1 → live pacing. Replay passes its multiplier so arcs shorten.
  spawnEvent(evt, speed = 1) {
    if (!this.globe || document.hidden) return;
    if (!evt.geo_ok) return;   // unknown origin: feed row only, no arc

    const key = `${evt.ip}|${evt.attack_type}`;
    const now = Date.now();
    const cool = IP_ARC_COOLDOWN / Math.max(1, Math.min(speed, 60));
    const last = this._cooldown.get(key) || 0;
    if (now - last < cool) return;
    this._cooldown.set(key, now);
    if (this._cooldown.size > 600) {
      for (const [k, t] of this._cooldown) {
        if (now - t > IP_ARC_COOLDOWN) this._cooldown.delete(k);
      }
    }

    const meta = sourceMeta(evt);
    const glow = meta.glow;
    const arc = {
      startLat: evt.lat, startLng: evt.lon,
      endLat: evt.target_lat ?? this.target.lat,
      endLng: evt.target_lon ?? this.target.lng,
      color: [`${glow}00`, `${glow}e6`, `${glow}00`],
      stroke: evt.type === 'crowdsec_ban' ? 0.75 : 0.5,
    };
    this.arcs.push(arc);
    if (this.arcs.length > ARCS_LIMIT) this.arcs = this.arcs.slice(-ARCS_LIMIT);
    this.globe.arcsData([...this.arcs]);

    const ttl = Math.max(1200, Math.min(LIVE_ARC_TTL / Math.max(1, speed / 4), LIVE_ARC_TTL));
    setTimeout(() => {
      this.arcs = this.arcs.filter((a) => a !== arc);
      this.globe.arcsData([...this.arcs]);
    }, ttl);

    // Impact ring at the target when the dash "lands".
    const hex = meta.glow.replace('#', '');
    const rgb = [0, 1, 2].map((i) => parseInt(hex.slice(i * 2, i * 2 + 2), 16)).join(',');
    const landDelay = REDUCED_MOTION ? 0 : 1100;
    setTimeout(() => {
      const ring = {
        lat: arc.endLat, lng: arc.endLng, rgb,
        max: evt.type === 'crowdsec_ban' ? 4.2 : 2.6,
      };
      this.rings.push(ring);
      this.globe.ringsData([...this.rings]);
      setTimeout(() => {
        this.rings = this.rings.filter((r) => r !== ring);
        this.globe.ringsData([...this.rings]);
      }, 2200);
    }, landDelay);
  }

  clear() {
    this.arcs = [];
    this.rings = [];
    this._cooldown.clear();
    if (this.globe) {
      this.globe.arcsData([]);
      this.globe.ringsData([]);
    }
  }
}
