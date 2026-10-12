// Polled data with loading/error state. Pauses while the app is in the
// background (phones suspend it anyway) and refreshes the moment it returns.

export class Poll<T> {
  data = $state<T | undefined>(undefined);
  error = $state<string | null>(null);
  loading = $state(true);
  updated = $state<number | null>(null);
  #timer: ReturnType<typeof setInterval> | undefined;
  #onVis = () => { if (document.visibilityState === 'visible') this.refresh(); };

  constructor(private fn: () => Promise<T>, private everyMs = 15000) {}

  async refresh() {
    try {
      this.data = await this.fn();
      this.error = null;
      this.updated = Date.now();
    } catch (e) {
      this.error = e instanceof Error ? e.message : String(e);
    } finally {
      this.loading = false;
    }
  }

  /** Call from an $effect; returns the cleanup. */
  start() {
    this.refresh();
    if (this.everyMs > 0) {
      this.#timer = setInterval(() => { if (document.visibilityState === 'visible') this.refresh(); }, this.everyMs);
    }
    document.addEventListener('visibilitychange', this.#onVis);
    return () => {
      clearInterval(this.#timer);
      document.removeEventListener('visibilitychange', this.#onVis);
    };
  }
}
