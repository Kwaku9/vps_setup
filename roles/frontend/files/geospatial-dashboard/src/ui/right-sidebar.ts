import { ShaderManager, VisionMode } from "@/shaders/postprocess";
import { LayerManager, LayerName } from "@/layers/layer-manager";
import { ControlsPanel } from "@/ui/controls-panel";
import { makeRetractable, PanelToggleState } from "@/ui/panel-base";

interface Preset {
  name: string;
  description: string;
  mode: VisionMode;
  layers: Partial<Record<LayerName, boolean>>;
}

const PRESETS: Preset[] = [
  {
    name: "DAY",
    description: "Standard view - flights & earthquakes",
    mode: "normal",
    layers: {
      flights: true,
      earthquakes: true,
      satellites: false,
      military: false,
      weather: true,
      cctv: false,
      traffic: false,
      firms: false,
      acled: false,
    },
  },
  {
    name: "NIGHT",
    description: "NVG mode - flights & satellites",
    mode: "nvg",
    layers: {
      flights: true,
      satellites: true,
      earthquakes: false,
      military: false,
      weather: false,
      cctv: false,
      traffic: false,
      firms: false,
      acled: false,
    },
  },
  {
    name: "TACTICAL",
    description: "FLIR mode - military, satellites, conflicts",
    mode: "flir",
    layers: {
      military: true,
      satellites: true,
      flights: false,
      earthquakes: false,
      weather: false,
      cctv: false,
      traffic: false,
      firms: true,
      acled: true,
    },
  },
];

export class RightSidebar {
  private container: HTMLDivElement;
  private presetButtons: Map<string, HTMLButtonElement> = new Map();
  private activePreset: string | null = null;
  private panelState: PanelToggleState;

  constructor(
    private shaders: ShaderManager,
    private layers: LayerManager,
    private controls: ControlsPanel
  ) {
    this.container = document.createElement("div");
    Object.assign(this.container.style, {
      position: "absolute",
      top: "12px",
      right: "12px",
      backgroundColor: "rgba(0, 0, 0, 0.85)",
      border: "1px solid #1a3a1a",
      borderRadius: "4px",
      padding: "10px",
      fontFamily: '"Courier New", monospace',
      fontSize: "10px",
      color: "#00ff41",
      zIndex: "1000",
      minWidth: "140px",
      userSelect: "none",
    });

    this.buildPanel();

    const { wrapper, state } = makeRetractable(this.container, 'right', 'wv_panel_presets');
    this.panelState = state;
    document.body.appendChild(wrapper);
  }

  toggle(): void {
    this.panelState.toggle();
  }

  private buildPanel(): void {
    const title = document.createElement("div");
    title.textContent = "PRESETS";
    Object.assign(title.style, {
      fontSize: "9px",
      letterSpacing: "2px",
      opacity: "0.5",
      marginBottom: "8px",
    });
    this.container.appendChild(title);

    for (const preset of PRESETS) {
      const btn = document.createElement("button");
      btn.textContent = preset.name;
      Object.assign(btn.style, {
        display: "block",
        width: "100%",
        background: "rgba(0, 40, 0, 0.5)",
        border: "1px solid #1a3a1a",
        color: "#00ff41",
        fontFamily: '"Courier New", monospace',
        fontSize: "11px",
        padding: "6px 10px",
        cursor: "pointer",
        borderRadius: "2px",
        marginBottom: "4px",
        textAlign: "left",
        letterSpacing: "2px",
      });

      const desc = document.createElement("div");
      desc.textContent = preset.description;
      Object.assign(desc.style, {
        fontSize: "8px",
        opacity: "0.5",
        marginTop: "2px",
      });
      btn.appendChild(desc);

      btn.addEventListener("mouseenter", () => {
        if (this.activePreset !== preset.name) {
          btn.style.background = "rgba(0, 80, 0, 0.7)";
        }
      });
      btn.addEventListener("mouseleave", () => {
        if (this.activePreset !== preset.name) {
          btn.style.background = "rgba(0, 40, 0, 0.5)";
        }
      });

      btn.addEventListener("click", () => this.applyPreset(preset));
      this.presetButtons.set(preset.name, btn);
      this.container.appendChild(btn);
    }
  }

  private applyPreset(preset: Preset): void {
    this.shaders.setMode(preset.mode);
    this.controls.updateActiveMode(preset.mode);

    for (const [name, visible] of Object.entries(preset.layers)) {
      const layer = this.layers[name as LayerName];
      if (layer && layer.visible !== visible) {
        layer.setVisible(visible as boolean);
      }
    }
    this.controls.updateLayers(this.layers.getStatus());

    this.activePreset = preset.name;
    for (const [name, btn] of this.presetButtons) {
      if (name === preset.name) {
        btn.style.border = "1px solid #00ff41";
        btn.style.background = "rgba(0, 60, 0, 0.8)";
        btn.style.color = "#ffffff";
      } else {
        btn.style.border = "1px solid #1a3a1a";
        btn.style.background = "rgba(0, 40, 0, 0.5)";
        btn.style.color = "#00ff41";
      }
    }
  }

  destroy(): void {
    this.container.remove();
  }
}
