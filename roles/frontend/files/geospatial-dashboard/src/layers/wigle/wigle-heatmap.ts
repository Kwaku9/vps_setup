import {
  Viewer,
  Cartesian3,
  SceneTransforms,
  Math as CesiumMath,
} from "cesium";
import { WigleNetwork } from "./wigle-api";

export class WigleHeatmap {
  private canvas: HTMLCanvasElement;
  private ctx: CanvasRenderingContext2D;
  private networks: WigleNetwork[] = [];
  private _active = false;
  private postRenderRemove: (() => void) | null = null;

  constructor(private viewer: Viewer) {
    this.canvas = document.createElement("canvas");
    Object.assign(this.canvas.style, {
      position: "absolute",
      top: "0",
      left: "0",
      width: "100%",
      height: "100%",
      pointerEvents: "none",
      zIndex: "998",
    });
    this.ctx = this.canvas.getContext("2d")!;
    document.body.appendChild(this.canvas);
    this.canvas.style.display = "none";

    // Resize canvas to match viewport
    this.resize();
    window.addEventListener("resize", () => this.resize());
  }

  private resize(): void {
    this.canvas.width = window.innerWidth;
    this.canvas.height = window.innerHeight;
  }

  setNetworks(networks: WigleNetwork[]): void {
    this.networks = networks;
  }

  activate(): void {
    if (this._active) return;
    this._active = true;
    this.canvas.style.display = "";

    this.postRenderRemove =
      this.viewer.scene.postRender.addEventListener(() => this.render());
  }

  deactivate(): void {
    if (!this._active) return;
    this._active = false;
    this.canvas.style.display = "none";
    this.networks = [];
    if (this.postRenderRemove) {
      this.postRenderRemove();
      this.postRenderRemove = null;
    }
    this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
  }

  get active(): boolean {
    return this._active;
  }

  private render(): void {
    const ctx = this.ctx;
    const w = this.canvas.width;
    const h = this.canvas.height;

    ctx.clearRect(0, 0, w, h);
    if (this.networks.length === 0) return;

    // Use additive blending for density visualization
    ctx.globalCompositeOperation = "lighter";

    for (const net of this.networks) {
      if (!net.lat || !net.lon) continue;

      const cartesian = Cartesian3.fromDegrees(net.lon, net.lat, 10);
      const screenPos = SceneTransforms.worldToWindowCoordinates(
        this.viewer.scene,
        cartesian
      );

      if (!screenPos) continue;
      if (screenPos.x < -50 || screenPos.x > w + 50) continue;
      if (screenPos.y < -50 || screenPos.y > h + 50) continue;

      // Determine glow color and weight by type
      let r: number, g: number, b: number, radius: number;
      if (net.type === "cell") {
        r = 0; g = 200; b = 255; radius = 30;
      } else if (net.type === "bt") {
        r = 200; g = 0; b = 255; radius = 15;
      } else {
        r = 0; g = 255; b = 65; radius = 20;
      }

      const gradient = ctx.createRadialGradient(
        screenPos.x,
        screenPos.y,
        0,
        screenPos.x,
        screenPos.y,
        radius
      );
      gradient.addColorStop(0, `rgba(${r}, ${g}, ${b}, 0.3)`);
      gradient.addColorStop(0.4, `rgba(${r}, ${g}, ${b}, 0.15)`);
      gradient.addColorStop(1, `rgba(${r}, ${g}, ${b}, 0)`);

      ctx.fillStyle = gradient;
      ctx.fillRect(
        screenPos.x - radius,
        screenPos.y - radius,
        radius * 2,
        radius * 2
      );
    }

    ctx.globalCompositeOperation = "source-over";
  }

  destroy(): void {
    this.deactivate();
    this.canvas.remove();
  }
}
