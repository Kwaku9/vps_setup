import { POI_LIST, POI } from "@/globe/poi";
import { CameraController } from "@/globe/camera";
import { makeRetractable, PanelToggleState } from "@/ui/panel-base";

export class LocationsBar {
  private container: HTMLDivElement;
  private panelState: PanelToggleState;

  constructor(private camera: CameraController) {
    this.container = document.createElement("div");
    Object.assign(this.container.style, {
      position: "absolute",
      top: "24px",
      left: "50%",
      transform: "translateX(-50%)",
      display: "flex",
      gap: "6px",
      alignItems: "center",
      zIndex: "1000",
      fontFamily: '"Courier New", monospace',
      fontSize: "10px",
      userSelect: "none",
      flexWrap: "wrap",
      justifyContent: "center",
      maxWidth: "90vw",
    });

    this.buildBar();

    const { wrapper, state } = makeRetractable(this.container, 'up');
    this.panelState = state;
    document.body.appendChild(wrapper);
  }

  toggle(): void {
    this.panelState.toggle();
  }

  private buildBar(): void {
    const cities = POI_LIST.filter((p) => p.group === "CITIES");
    const landmarks = POI_LIST.filter((p) => p.group === "LANDMARKS");

    if (cities.length > 0) {
      this.addGroupLabel("CITIES");
      for (const poi of cities) {
        this.addButton(poi);
      }
    }

    if (landmarks.length > 0) {
      this.addSeparator();
      this.addGroupLabel("LANDMARKS");
      for (const poi of landmarks) {
        this.addButton(poi);
      }
    }
  }

  private addGroupLabel(text: string): void {
    const label = document.createElement("span");
    label.textContent = text;
    Object.assign(label.style, {
      color: "#00ff41",
      opacity: "0.5",
      letterSpacing: "2px",
      fontSize: "9px",
      marginRight: "2px",
    });
    this.container.appendChild(label);
  }

  private addSeparator(): void {
    const sep = document.createElement("span");
    sep.textContent = "|";
    Object.assign(sep.style, {
      color: "#1a3a1a",
      margin: "0 4px",
    });
    this.container.appendChild(sep);
  }

  private addButton(poi: POI): void {
    const btn = document.createElement("button");
    const keyHint = poi.key ? " [" + poi.key.toUpperCase() + "]" : "";
    btn.textContent = poi.name + keyHint;
    Object.assign(btn.style, {
      background: "rgba(0, 0, 0, 0.75)",
      border: "1px solid #1a3a1a",
      color: "#00ff41",
      fontFamily: '"Courier New", monospace',
      fontSize: "10px",
      padding: "4px 10px",
      cursor: "pointer",
      borderRadius: "12px",
      whiteSpace: "nowrap",
      letterSpacing: "0.5px",
    });
    btn.addEventListener("mouseenter", () => {
      btn.style.background = "rgba(0, 80, 0, 0.7)";
      btn.style.borderColor = "#33ff33";
    });
    btn.addEventListener("mouseleave", () => {
      btn.style.background = "rgba(0, 0, 0, 0.75)";
      btn.style.borderColor = "#1a3a1a";
    });
    btn.addEventListener("click", () => {
      this.camera.flyTo(poi.target);
    });
    this.container.appendChild(btn);
  }

  destroy(): void {
    this.container.remove();
  }
}
