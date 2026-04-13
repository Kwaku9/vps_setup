import { Scene } from 'cesium';

export class EffectsManager {
  private bloomEnabled = false;

  constructor(private scene: Scene) {}

  toggleBloom(): boolean {
    this.bloomEnabled = !this.bloomEnabled;
    this.scene.postProcessStages.bloom.enabled = this.bloomEnabled;
    this.scene.requestRender();
    return this.bloomEnabled;
  }

  setBloom(enabled: boolean): void {
    this.bloomEnabled = enabled;
    this.scene.postProcessStages.bloom.enabled = enabled;
    this.scene.requestRender();
  }
}
