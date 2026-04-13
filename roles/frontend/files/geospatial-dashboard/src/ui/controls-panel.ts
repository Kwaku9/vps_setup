import { VisionMode } from "@/shaders/postprocess";
import { LayerStatus } from "@/layers/layer-manager";
import { makeRetractable, PanelToggleState } from "@/ui/panel-base";

export class ControlsPanel {
  private container: HTMLDivElement;
  private modeButtons: Map<VisionMode, HTMLButtonElement> = new Map();
  private layerButtons: Map<string, HTMLButtonElement> = new Map();
  private panelState: PanelToggleState;

  private onModeChange: (mode: VisionMode) => void = () => {};
  private onLayerToggle: (name: string) => void = () => {};
  private onBloomToggle: () => void = () => {};

  constructor() {
    this.container = document.createElement("div");
    Object.assign(this.container.style, {
      position: "absolute",
      top: "12px",
      left: "12px",
      backgroundColor: "rgba(0, 0, 0, 0.85)",
      border: "1px solid #1a3a1a",
      borderRadius: "4px",
      padding: "12px",
      fontFamily: '"Courier New", monospace',
      fontSize: "11px",
      color: "#33ff33",
      zIndex: "1000",
      minWidth: "200px",
      userSelect: "none",
    });

    this.buildPanel();

    const { wrapper, state } = makeRetractable(this.container, 'left');
    this.panelState = state;
    document.body.appendChild(wrapper);
  }

  toggle(): void {
    this.panelState.toggle();
  }

  private buildPanel(): void {
    // Title
    const title = document.createElement("div");
    title.textContent = "WORLDVIEW";
    Object.assign(title.style, {
      fontSize: "14px",
      fontWeight: "bold",
      letterSpacing: "3px",
      marginBottom: "10px",
      borderBottom: "1px solid #1a3a1a",
      paddingBottom: "6px",
    });
    this.container.appendChild(title);

    // Vision mode section
    this.addSectionLabel("VISION MODE");
    const modes: { mode: VisionMode; label: string; key: string }[] = [
      { mode: "normal", label: "NORMAL", key: "1" },
      { mode: "crt", label: "CRT", key: "2" },
      { mode: "nvg", label: "NVG", key: "3" },
      { mode: "flir", label: "FLIR", key: "4" },
    ];

    const modeRow = document.createElement("div");
    modeRow.style.display = "flex";
    modeRow.style.gap = "4px";
    modeRow.style.marginBottom = "10px";

    for (const { mode, label, key } of modes) {
      const btn = this.createButton(
        `[${key}] ${label}`,
        () => this.onModeChange(mode)
      );
      this.modeButtons.set(mode, btn);
      modeRow.appendChild(btn);
    }
    this.container.appendChild(modeRow);

    // Bloom toggle
    const bloomBtn = this.createButton("BLOOM: OFF", () =>
      this.onBloomToggle()
    );
    bloomBtn.id = "bloom-toggle";
    bloomBtn.style.marginBottom = "10px";
    bloomBtn.style.display = "block";
    this.container.appendChild(bloomBtn);

    // Layers section
    this.addSectionLabel("LAYERS");
    const layers = [
      "Satellites",
      "Flights",
      "Military",
      "Earthquakes",
      "Weather",
      "CCTV",
      "Traffic",
      "WiGLE",
      "FIRMS",
      "ACLED",
      "Threats",
      "Maritime",
      "Artemis",
    ];
    for (const name of layers) {
      const btn = this.createButton(`${name}: --`, () =>
        this.onLayerToggle(name.toLowerCase())
      );
      this.layerButtons.set(name, btn);
      btn.style.display = "block";
      btn.style.marginBottom = "3px";
      btn.style.width = "100%";
      btn.style.textAlign = "left";
      this.container.appendChild(btn);
    }

    // POI hint
    this.addSectionLabel("POI KEYS");
    const poiHint = document.createElement("div");
    poiHint.textContent =
      "Q=Pentagon W=Kremlin E=WhiteHouse R=Area51 T=TimesSquare";
    poiHint.style.opacity = "0.6";
    poiHint.style.lineHeight = "1.4";
    this.container.appendChild(poiHint);

    // Layer keys hint
    this.addSectionLabel("LAYER KEYS");
    const layerHint = document.createElement("div");
    layerHint.textContent = "B=Bloom C=CCTV V=Traffic G=WiGLE X=FIRMS Z=ACLED 9=Threats 6=Maritime A=Artemis";
    layerHint.style.opacity = "0.6";
    layerHint.style.lineHeight = "1.4";
    this.container.appendChild(layerHint);

    // Panel keys hint
    this.addSectionLabel("PANEL KEYS");
    const panelHint = document.createElement("div");
    panelHint.textContent = "[=Left ]=Right \=Params /=Locations H=HUD";
    panelHint.style.opacity = "0.6";
    panelHint.style.lineHeight = "1.4";
    this.container.appendChild(panelHint);
  }

  private addSectionLabel(text: string): void {
    const label = document.createElement("div");
    label.textContent = text;
    Object.assign(label.style, {
      fontSize: "9px",
      letterSpacing: "2px",
      opacity: "0.5",
      marginBottom: "4px",
      marginTop: "4px",
    });
    this.container.appendChild(label);
  }

  private createButton(
    text: string,
    onClick: () => void
  ): HTMLButtonElement {
    const btn = document.createElement("button");
    btn.textContent = text;
    Object.assign(btn.style, {
      background: "rgba(0, 40, 0, 0.5)",
      border: "1px solid #1a3a1a",
      color: "#33ff33",
      fontFamily: '"Courier New", monospace',
      fontSize: "10px",
      padding: "4px 8px",
      cursor: "pointer",
      borderRadius: "2px",
    });
    btn.addEventListener("mouseenter", () => {
      btn.style.background = "rgba(0, 80, 0, 0.7)";
    });
    btn.addEventListener("mouseleave", () => {
      btn.style.background = "rgba(0, 40, 0, 0.5)";
    });
    btn.addEventListener("click", onClick);
    return btn;
  }

  setOnModeChange(handler: (mode: VisionMode) => void): void {
    this.onModeChange = handler;
  }

  setOnLayerToggle(handler: (name: string) => void): void {
    this.onLayerToggle = handler;
  }

  setOnBloomToggle(handler: () => void): void {
    this.onBloomToggle = handler;
  }

  updateActiveMode(mode: VisionMode): void {
    for (const [m, btn] of this.modeButtons) {
      btn.style.border =
        m === mode ? "1px solid #33ff33" : "1px solid #1a3a1a";
      btn.style.color = m === mode ? "#ffffff" : "#33ff33";
    }
  }

  updateLayers(statuses: LayerStatus[]): void {
    for (const status of statuses) {
      const btn = this.layerButtons.get(status.name);
      if (btn) {
        const state = status.visible ? "ON" : "OFF";
        btn.textContent = `${status.name}: ${state} (${status.count})`;
        btn.style.opacity = status.visible ? "1" : "0.5";
      }
    }
  }

  updateBloom(enabled: boolean): void {
    const btn = document.getElementById("bloom-toggle") as HTMLButtonElement;
    if (btn) {
      btn.textContent = `BLOOM: ${enabled ? "ON" : "OFF"}`;
    }
  }
}
