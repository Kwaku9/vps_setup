import { PostProcessStage, PostProcessStageCollection, Scene } from 'cesium';
import crtSource from './crt.glsl?raw';
import nvgSource from './nvg.glsl?raw';
import flirSource from './flir.glsl?raw';

export type VisionMode = 'normal' | 'crt' | 'nvg' | 'flir';

export class ShaderManager {
  private stages = new Map<VisionMode, PostProcessStage>();
  private currentMode: VisionMode = 'normal';
  private startTime = Date.now();

  constructor(private scene: Scene) {
    this.stages.set(
      'crt',
      new PostProcessStage({
        fragmentShader: crtSource,
        uniforms: {
          time: () => (Date.now() - this.startTime) / 1000,
        },
      })
    );

    this.stages.set(
      'nvg',
      new PostProcessStage({
        fragmentShader: nvgSource,
        uniforms: {
          time: () => (Date.now() - this.startTime) / 1000,
        },
      })
    );

    this.stages.set(
      'flir',
      new PostProcessStage({
        fragmentShader: flirSource,
      })
    );

    // Add all stages (disabled by default)
    for (const stage of this.stages.values()) {
      stage.enabled = false;
      this.scene.postProcessStages.add(stage);
    }
  }

  setMode(mode: VisionMode): void {
    // Disable current
    if (this.currentMode !== 'normal') {
      const prev = this.stages.get(this.currentMode);
      if (prev) prev.enabled = false;
    }

    // Enable new
    if (mode !== 'normal') {
      const next = this.stages.get(mode);
      if (next) next.enabled = true;
    }

    this.currentMode = mode;

    // Force render for animated shaders
    this.scene.requestRender();

    // For animated modes, need continuous rendering
    if (mode === 'crt' || mode === 'nvg') {
      this.scene.requestRenderMode = false;
    } else {
      this.scene.requestRenderMode = true;
    }
  }

  getMode(): VisionMode {
    return this.currentMode;
  }

  toggle(): void {
    const modes: VisionMode[] = ['normal', 'crt', 'nvg', 'flir'];
    const idx = modes.indexOf(this.currentMode);
    this.setMode(modes[(idx + 1) % modes.length]);
  }
}
