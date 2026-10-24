// Click-to-track lock-on, after God's Eye View's tracked camera
// (github.com/bilawalsidhu/gods-eye-view, MIT): the camera orbits a locked
// target and keeps it centred, with Tilt and North Up controls, and can
// circle it (Orbit). Threats and POIs are fixed points, so this is a Cesium
// lookAt frame rather than their moving-target tracker.
import {
  Viewer,
  Entity,
  Cartesian3,
  BoundingSphere,
  HeadingPitchRange,
  Matrix4,
  EasingFunction,
  Math as CesiumMath,
} from "cesium";

export type TiltMode = "oblique" | "top";

const TOP_PITCH = -90;
const OBLIQUE_PITCH = -35;
const DEFAULT_RANGE = 800_000;
const MIN_RANGE = 2_000;
/** Orbit speed: one lap every two minutes. */
const ORBIT_RATE = (2 * Math.PI) / 120;
const ORBIT_PREF_KEY = "wv_orbit";

/** What is locked: a threat entity, or a fixed point such as a POI. */
export type LockTarget =
  | { kind: "threat"; entity: Entity }
  | { kind: "poi"; key: string; position: Cartesian3 };

export interface LockState {
  target: LockTarget;
  /** Label shown in the lock bar (threat IP or POI name). For threats it is
   *  also the share-link id. */
  id: string;
  range: number;
  heading: number;
  /** Current pitch in degrees. */
  pitch: number;
  /** The angled pitch Tilt returns to from top-down (a POI's own framing). */
  obliquePitch: number;
  orbiting: boolean;
}

export interface LockOptions {
  range?: number;
  heading?: number;
  tilt?: TiltMode;
  /** Explicit oblique pitch (POIs carry their own framing). */
  pitch?: number;
  fly?: boolean;
  /** Orbit after arriving; defaults to the remembered preference. */
  orbit?: boolean;
}

export class TargetLock {
  private state: LockState | null = null;
  /** True once the camera is in the target's lookAt frame. */
  private framed = false;
  private dragging = false;
  private lastTick = 0;
  private bar: HTMLDivElement;
  private label: HTMLSpanElement;
  private tiltBtn: HTMLButtonElement;
  private orbitBtn: HTMLButtonElement;
  private listeners: ((state: LockState | null) => void)[] = [];

  constructor(private viewer: Viewer) {
    this.bar = document.createElement("div");
    this.bar.classList.add("wv-hud-panel");
    Object.assign(this.bar.style, {
      position: "absolute",
      top: "calc(26px + env(safe-area-inset-top, 0px))",
      left: "50%",
      transform: "translateX(-50%)",
      // Shown/hidden via display, not the hidden attribute: an inline
      // display:flex would override [hidden] and leave the bar on screen.
      display: "none",
      alignItems: "center",
      gap: "6px",
      padding: "4px 8px",
      background: "rgba(0,0,0,0.85)",
      border: "1px solid #ff3b3b",
      borderRadius: "3px",
      fontFamily: '"Courier New", monospace',
      fontSize: "10px",
      color: "#ff3b3b",
      zIndex: "1001",
      userSelect: "none",
    });

    this.label = document.createElement("span");
    this.label.style.letterSpacing = "1px";
    this.bar.appendChild(this.label);
    this.orbitBtn = this.button("⟳ ORBIT", () => this.toggleOrbit());
    this.bar.appendChild(this.orbitBtn);
    this.tiltBtn = this.button("TILT", () => this.toggleTilt());
    this.bar.appendChild(this.tiltBtn);
    this.bar.appendChild(this.button("N↑", () => this.northUp()));
    this.bar.appendChild(this.button("✕", () => this.unlock()));
    document.body.appendChild(this.bar);

    document.addEventListener("keydown", (e) => {
      if ((e.target as HTMLElement).tagName === "INPUT") return;
      if (e.key === "Escape" && this.state) this.unlock();
    });

    // Orbit yields to the user's hand: no circling while dragging.
    const canvas = viewer.scene.canvas;
    canvas.addEventListener("pointerdown", () => (this.dragging = true));
    window.addEventListener("pointerup", () => {
      this.dragging = false;
      this.syncFromCamera();
    });

    viewer.clock.onTick.addEventListener(() => this.tick());

    // Keep range/heading current as the user orbits and zooms, so Tilt,
    // North Up and share links start from what is on screen.
    viewer.camera.moveEnd.addEventListener(() => this.syncFromCamera());
  }

  get current(): LockState | null {
    return this.state;
  }

  get isLocked(): boolean {
    return this.state !== null;
  }

  onChange(listener: (state: LockState | null) => void): void {
    this.listeners.push(listener);
  }

  /** Fly to a threat entity, then hold the camera on it. */
  lock(entity: Entity, id: string, opts: LockOptions = {}): void {
    this.lockTarget({ kind: "threat", entity }, id, opts);
  }

  /** Fly to a fixed point (a POI), then hold the camera on it. */
  lockPoint(position: Cartesian3, key: string, name: string, opts: LockOptions = {}): void {
    this.lockTarget({ kind: "poi", key, position }, name, opts);
  }

  private lockTarget(target: LockTarget, id: string, opts: LockOptions): void {
    const position = this.positionOf(target);
    if (!position) return;
    this.releaseFrame();
    // Each target brings its own framing (a POI's authored tilt); never
    // inherit the previous target's.
    const obliquePitch = opts.pitch ?? OBLIQUE_PITCH;
    const tilt = opts.tilt ?? (this.state && this.state.pitch === TOP_PITCH ? "top" : "oblique");
    this.state = {
      target,
      id,
      range: opts.range ?? this.state?.range ?? DEFAULT_RANGE,
      heading: opts.heading ?? 0,
      pitch: tilt === "top" ? TOP_PITCH : obliquePitch,
      obliquePitch,
      orbiting: opts.orbit ?? this.orbitPreferred(),
    };
    this.label.textContent = target.kind === "threat" ? `LOCK ${id}` : `◎ ${id.toUpperCase()}`;
    this.refreshButtons();
    this.bar.style.display = "flex";
    this.framed = false;

    const state = this.state;
    const offset = this.offset();
    if (opts.fly === false) {
      this.viewer.camera.lookAt(position, offset);
      this.framed = true;
      this.emit();
      return;
    }
    this.viewer.camera.flyToBoundingSphere(new BoundingSphere(position, 0), {
      offset,
      easingFunction: EasingFunction.QUADRATIC_IN_OUT,
      complete: () => {
        // A newer lock or an unlock may have happened mid-flight.
        if (this.state === state) {
          this.viewer.camera.lookAt(position, this.offset());
          this.framed = true;
          this.lastTick = 0;
        }
      },
    });
    this.emit();
  }

  unlock(): void {
    if (!this.state) return;
    this.releaseFrame();
    this.state = null;
    this.framed = false;
    this.bar.style.display = "none";
    this.emit();
  }

  toggleOrbit(): void {
    if (!this.state) return;
    this.syncFromCamera();
    this.state.orbiting = !this.state.orbiting;
    this.lastTick = 0;
    try { localStorage.setItem(ORBIT_PREF_KEY, this.state.orbiting ? "1" : "0"); }
    catch { /* private mode */ }
    this.refreshButtons();
    this.emit();
  }

  toggleTilt(): void {
    if (!this.state) return;
    this.syncFromCamera();
    this.state.pitch = this.state.pitch === TOP_PITCH ? this.state.obliquePitch : TOP_PITCH;
    this.refreshButtons();
    this.reframe();
  }

  northUp(): void {
    if (!this.state) return;
    this.syncFromCamera();
    this.state.heading = 0;
    this.reframe();
  }

  get tilt(): TiltMode | null {
    return this.state ? (this.state.pitch === TOP_PITCH ? "top" : "oblique") : null;
  }

  private tick(): void {
    const now = performance.now();
    const dt = this.lastTick ? (now - this.lastTick) / 1000 : 0;
    this.lastTick = now;
    if (!this.state?.orbiting || !this.framed || this.dragging) return;
    if (dt <= 0 || dt > 1) return; // first frame, or the tab was hidden
    // In the lookAt frame this turns the camera around the target's
    // vertical axis: a level circle at constant range and tilt.
    this.viewer.camera.rotateRight(ORBIT_RATE * dt);
  }

  /** Read range/heading back from the camera after the user (or the
   *  orbit) moved it. Ignored until the lock flight lands: mid-flight
   *  distances would be saved as the zoom (a share link once captured
   *  23,500 km). */
  private syncFromCamera(): void {
    if (!this.state || !this.framed) return;
    const target = this.targetPosition();
    if (!target) return;
    this.state.range = Math.max(
      MIN_RANGE,
      Cartesian3.distance(this.viewer.camera.positionWC, target)
    );
    this.state.heading =
      CesiumMath.toDegrees(CesiumMath.zeroToTwoPi(this.viewer.camera.heading)) % 360;
    this.emit();
  }

  private orbitPreferred(): boolean {
    try { return localStorage.getItem(ORBIT_PREF_KEY) === "1"; }
    catch { return false; }
  }

  private refreshButtons(): void {
    const s = this.state;
    if (!s) return;
    this.tiltBtn.textContent = s.pitch === TOP_PITCH ? `TILT ${Math.round(-s.obliquePitch)}°` : "TILT 90°";
    this.orbitBtn.textContent = s.orbiting ? "■ STOP" : "⟳ ORBIT";
    this.orbitBtn.style.borderColor = s.orbiting ? "#ff3b3b" : "#7a1c1c";
  }

  private reframe(): void {
    const target = this.targetPosition();
    if (!target) return;
    this.viewer.camera.lookAt(target, this.offset());
    this.emit();
  }

  private offset(): HeadingPitchRange {
    const s = this.state!;
    return new HeadingPitchRange(
      CesiumMath.toRadians(s.heading),
      CesiumMath.toRadians(s.pitch),
      s.range
    );
  }

  private positionOf(target: LockTarget): Cartesian3 | undefined {
    return target.kind === "threat"
      ? target.entity.position?.getValue(this.viewer.clock.currentTime)
      : target.position;
  }

  private targetPosition(): Cartesian3 | undefined {
    return this.state ? this.positionOf(this.state.target) : undefined;
  }

  /** Return the camera to the normal globe frame so free navigation works. */
  private releaseFrame(): void {
    this.viewer.camera.lookAtTransform(Matrix4.IDENTITY);
  }

  private emit(): void {
    for (const l of this.listeners) l(this.state);
  }

  private button(text: string, onClick: () => void): HTMLButtonElement {
    const b = document.createElement("button");
    b.textContent = text;
    Object.assign(b.style, {
      background: "rgba(60,0,0,0.6)",
      border: "1px solid #7a1c1c",
      color: "#ff6b6b",
      fontFamily: '"Courier New", monospace',
      fontSize: "10px",
      padding: "2px 6px",
      cursor: "pointer",
      borderRadius: "2px",
    });
    b.addEventListener("click", onClick);
    return b;
  }
}
