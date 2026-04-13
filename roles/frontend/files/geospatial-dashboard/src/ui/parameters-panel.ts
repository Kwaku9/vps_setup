import { Scene, PostProcessStage } from "cesium";
import { makeRetractable, PanelToggleState } from "@/ui/panel-base";

export interface ParameterValues {
  sensitivity: number;
  bloom: number;
  pixelation: number;
  whot: boolean;
}

export class ParametersPanel {
  private container: HTMLDivElement;
  private sensitivityStage: PostProcessStage | null = null;
  private pixelateStage: PostProcessStage | null = null;
  private panelState: PanelToggleState;
  private values: ParameterValues = {
    sensitivity: 1.0,
    bloom: 0.0,
    pixelation: 1,
    whot: true,
  };

  constructor(private scene: Scene) {
    this.container = document.createElement("div");
    Object.assign(this.container.style, {
      position: "absolute",
      bottom: "60px",
      left: "12px",
      backgroundColor: "rgba(0, 0, 0, 0.85)",
      border: "1px solid #1a3a1a",
      borderRadius: "4px",
      padding: "10px",
      fontFamily: '"Courier New", monospace',
      fontSize: "10px",
      color: "#00ff41",
      zIndex: "1000",
      minWidth: "200px",
      userSelect: "none",
    });

    this.buildPanel();
    this.initPostProcessStages();

    const { wrapper, state } = makeRetractable(this.container, 'left');
    this.panelState = state;
    document.body.appendChild(wrapper);
  }

  toggle(): void {
    this.panelState.toggle();
  }

  private buildPanel(): void {
    const title = document.createElement("div");
    title.textContent = "PARAMETERS";
    Object.assign(title.style, {
      fontSize: "9px",
      letterSpacing: "2px",
      opacity: "0.5",
      marginBottom: "8px",
    });
    this.container.appendChild(title);

    this.addSlider("SENSITIVITY", 0, 2, 0.1, this.values.sensitivity, (v) => {
      this.values.sensitivity = v;
      this.updateSensitivity();
    });

    this.addSlider("BLOOM", 0, 1, 0.05, this.values.bloom, (v) => {
      this.values.bloom = v;
      this.updateBloom();
    });

    this.addSlider("PIXELATION", 1, 16, 1, this.values.pixelation, (v) => {
      this.values.pixelation = v;
      this.updatePixelation();
    });

    const toggleRow = document.createElement("div");
    Object.assign(toggleRow.style, {
      display: "flex",
      justifyContent: "space-between",
      alignItems: "center",
      marginTop: "6px",
    });

    const toggleLabel = document.createElement("span");
    toggleLabel.textContent = "THERMAL";
    toggleLabel.style.opacity = "0.6";

    const toggleBtn = document.createElement("button");
    toggleBtn.textContent = "WHOT";
    Object.assign(toggleBtn.style, {
      background: "rgba(0, 40, 0, 0.5)",
      border: "1px solid #1a3a1a",
      color: "#00ff41",
      fontFamily: '"Courier New", monospace',
      fontSize: "10px",
      padding: "2px 8px",
      cursor: "pointer",
      borderRadius: "2px",
    });
    toggleBtn.addEventListener("click", () => {
      this.values.whot = !this.values.whot;
      toggleBtn.textContent = this.values.whot ? "WHOT" : "BHOT";
    });

    toggleRow.appendChild(toggleLabel);
    toggleRow.appendChild(toggleBtn);
    this.container.appendChild(toggleRow);
  }

  private addSlider(
    label: string,
    min: number,
    max: number,
    step: number,
    initial: number,
    onChange: (value: number) => void
  ): void {
    const row = document.createElement("div");
    row.style.marginBottom = "6px";

    const labelRow = document.createElement("div");
    Object.assign(labelRow.style, {
      display: "flex",
      justifyContent: "space-between",
      marginBottom: "2px",
    });

    const nameEl = document.createElement("span");
    nameEl.textContent = label;
    nameEl.style.opacity = "0.6";

    const valueEl = document.createElement("span");
    valueEl.textContent = initial.toString();

    labelRow.appendChild(nameEl);
    labelRow.appendChild(valueEl);

    const slider = document.createElement("input");
    slider.type = "range";
    slider.min = min.toString();
    slider.max = max.toString();
    slider.step = step.toString();
    slider.value = initial.toString();
    Object.assign(slider.style, {
      width: "100%",
      accentColor: "#00ff41",
      height: "4px",
      cursor: "pointer",
    });

    slider.addEventListener("input", () => {
      const v = parseFloat(slider.value);
      valueEl.textContent = v.toFixed(step < 1 ? 1 : 0);
      onChange(v);
    });

    row.appendChild(labelRow);
    row.appendChild(slider);
    this.container.appendChild(row);
  }

  private initPostProcessStages(): void {
    const sensitivityShader = [
      "uniform sampler2D colorTexture;",
      "uniform float brightness;",
      "in vec2 v_textureCoordinates;",
      "void main() {",
      "  vec4 color = texture(colorTexture, v_textureCoordinates);",
      "  out_FragColor = vec4(color.rgb * brightness, color.a);",
      "}",
    ].join("\n");

    this.sensitivityStage = new PostProcessStage({
      fragmentShader: sensitivityShader,
      uniforms: {
        brightness: () => this.values.sensitivity,
      },
    });
    this.sensitivityStage.enabled = false;
    this.scene.postProcessStages.add(this.sensitivityStage);

    const pixelateShader = [
      "uniform sampler2D colorTexture;",
      "uniform float pixelSize;",
      "in vec2 v_textureCoordinates;",
      "void main() {",
      "  vec2 uv = v_textureCoordinates;",
      "  if (pixelSize > 1.0) {",
      "    vec2 size = vec2(textureSize(colorTexture, 0));",
      "    vec2 cellSize = vec2(pixelSize) / size;",
      "    uv = cellSize * floor(uv / cellSize) + cellSize * 0.5;",
      "  }",
      "  out_FragColor = texture(colorTexture, uv);",
      "}",
    ].join("\n");

    this.pixelateStage = new PostProcessStage({
      fragmentShader: pixelateShader,
      uniforms: {
        pixelSize: () => this.values.pixelation,
      },
    });
    this.pixelateStage.enabled = false;
    this.scene.postProcessStages.add(this.pixelateStage);
  }

  private updateSensitivity(): void {
    if (this.sensitivityStage) {
      this.sensitivityStage.enabled = this.values.sensitivity !== 1.0;
      this.scene.requestRender();
    }
  }

  private updateBloom(): void {
    const bloom = this.scene.postProcessStages.bloom;
    if (this.values.bloom > 0) {
      bloom.enabled = true;
      bloom.uniforms.glowOnly = false;
      bloom.uniforms.brightness = this.values.bloom * 0.5;
      bloom.uniforms.delta = 1.0;
      bloom.uniforms.sigma = 3.78;
      bloom.uniforms.stepSize = 5.0;
    } else {
      bloom.enabled = false;
    }
    this.scene.requestRender();
  }

  private updatePixelation(): void {
    if (this.pixelateStage) {
      this.pixelateStage.enabled = this.values.pixelation > 1;
      this.scene.requestRender();
    }
  }

  getValues(): ParameterValues {
    return { ...this.values };
  }

  destroy(): void {
    if (this.sensitivityStage) {
      this.scene.postProcessStages.remove(this.sensitivityStage);
    }
    if (this.pixelateStage) {
      this.scene.postProcessStages.remove(this.pixelateStage);
    }
    this.container.remove();
  }
}
