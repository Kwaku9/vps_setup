import { Viewer, Math as CesiumMath } from "cesium";

export class HUDOverlay {
  private container: HTMLDivElement;
  private topBanner: HTMLDivElement;
  private bottomBanner: HTMLDivElement;
  private coordsEl: HTMLDivElement;
  private altEl: HTMLDivElement;
  private timeEl: HTMLDivElement;
  private headingEl: HTMLDivElement;
  private removeListener: (() => void) | null = null;
  private _hudVisible = true;

  constructor(private viewer: Viewer) {
    this.container = document.createElement("div");
    Object.assign(this.container.style, {
      position: "absolute",
      top: "0",
      left: "0",
      width: "100%",
      height: "100%",
      pointerEvents: "none",
      zIndex: "999",
      fontFamily: '"Courier New", monospace',
    });

    // Top classification banner
    this.topBanner = this.createBanner();
    this.topBanner.textContent = "TOP SECRET // SCI // NOFORN";
    Object.assign(this.topBanner.style, {
      top: "0",
      backgroundColor: "rgba(180, 0, 0, 0.85)",
      color: "#fff",
      fontSize: "11px",
      fontWeight: "bold",
      letterSpacing: "3px",
      textAlign: "center",
      padding: "3px 0",
    });

    // Bottom classification banner
    this.bottomBanner = this.createBanner();
    this.bottomBanner.textContent = "WORLDVIEW // UNCLASSIFIED // FOUO";
    Object.assign(this.bottomBanner.style, {
      bottom: "0",
      backgroundColor: "rgba(0, 80, 0, 0.7)",
      color: "#00ff41",
      fontSize: "10px",
      letterSpacing: "2px",
      textAlign: "center",
      padding: "3px 0",
    });

    // Bottom-left: coords + altitude
    const bottomLeft = document.createElement("div");
    Object.assign(bottomLeft.style, {
      position: "absolute",
      bottom: "28px",
      left: "12px",
      color: "#00ff41",
      fontSize: "11px",
      textShadow: "0 0 6px rgba(0, 255, 65, 0.5)",
      lineHeight: "1.5",
    });

    this.coordsEl = document.createElement("div");
    this.altEl = document.createElement("div");
    bottomLeft.appendChild(this.coordsEl);
    bottomLeft.appendChild(this.altEl);

    // Bottom-right: time + heading
    const bottomRight = document.createElement("div");
    Object.assign(bottomRight.style, {
      position: "absolute",
      bottom: "28px",
      right: "12px",
      color: "#00ff41",
      fontSize: "11px",
      textAlign: "right",
      textShadow: "0 0 6px rgba(0, 255, 65, 0.5)",
      lineHeight: "1.5",
    });

    this.timeEl = document.createElement("div");
    this.headingEl = document.createElement("div");
    bottomRight.appendChild(this.timeEl);
    bottomRight.appendChild(this.headingEl);

    this.container.appendChild(this.topBanner);
    this.container.appendChild(this.bottomBanner);
    this.container.appendChild(bottomLeft);
    this.container.appendChild(bottomRight);
    this.container.classList.add("wv-hud-panel");   // cinematic hide-all target
    document.body.appendChild(this.container);

    this.startUpdates();
  }

  toggle(): void {
    this._hudVisible = !this._hudVisible;
    this.container.style.display = this._hudVisible ? "" : "none";
  }

  private createBanner(): HTMLDivElement {
    const banner = document.createElement("div");
    Object.assign(banner.style, {
      position: "absolute",
      left: "0",
      width: "100%",
    });
    this.container.appendChild(banner);
    return banner;
  }

  private startUpdates(): void {
    const update = () => {
      this.updateReadouts();
    };
    this.removeListener = this.viewer.clock.onTick.addEventListener(update);
  }

  private updateReadouts(): void {
    const cam = this.viewer.camera;
    const carto = cam.positionCartographic;

    const lat = CesiumMath.toDegrees(carto.latitude);
    const lon = CesiumMath.toDegrees(carto.longitude);
    const alt = carto.height;
    const heading = CesiumMath.toDegrees(cam.heading);

    // Coords
    const latDir = lat >= 0 ? "N" : "S";
    const lonDir = lon >= 0 ? "E" : "W";
    this.coordsEl.textContent =
      "LAT " +
      Math.abs(lat).toFixed(4) +
      latDir +
      "  LON " +
      Math.abs(lon).toFixed(4) +
      lonDir;

    // Altitude
    if (alt > 1000000) {
      this.altEl.textContent = "ALT " + (alt / 1000).toFixed(0) + " km";
    } else if (alt > 1000) {
      this.altEl.textContent = "ALT " + (alt / 1000).toFixed(1) + " km";
    } else {
      this.altEl.textContent = "ALT " + alt.toFixed(0) + " m";
    }

    // Time
    const now = new Date();
    const utc = now.toISOString().replace("T", " ").substring(0, 19) + "Z";
    const local = now.toLocaleTimeString("en-US", { hour12: false });
    this.timeEl.textContent = "UTC " + utc + "  LOCAL " + local;

    // Heading
    const hdgStr = heading.toFixed(1).padStart(5, "0");
    this.headingEl.textContent =
      "HDG " + hdgStr + " " + this.headingToCardinal(heading);
  }

  private headingToCardinal(deg: number): string {
    const dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"];
    const idx = Math.round(deg / 45) % 8;
    return dirs[idx];
  }

  destroy(): void {
    if (this.removeListener) this.removeListener();
    this.container.remove();
  }
}
