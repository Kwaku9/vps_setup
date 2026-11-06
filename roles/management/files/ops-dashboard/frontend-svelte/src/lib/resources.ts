import type { Service } from './types';

export type Pressure = 'cool' | 'warm' | 'hot' | 'unknown' | 'off';
export const pressureColors: Record<Pressure, string> = {
  cool: '#6FCF97', warm: '#F2BA62', hot: '#FF7B80', unknown: '#687787', off: '#46515D',
};
const valid = (n: unknown): n is number => typeof n === 'number' && Number.isFinite(n) && n >= 0;
export const pressure = (n: number | null): Pressure => n == null ? 'unknown' : n >= 85 ? 'hot' : n >= 60 ? 'warm' : 'cool';

export function serviceResources(s: Service, now = Date.now()) {
  // Host/remote endpoint status is available, but container load isn't measured there.
  const fresh = s.platform === 'vps' && s.status === 'running' && valid(s.metrics_at) &&
    now / 1000 - s.metrics_at < 90 && s.metrics_at <= now / 1000 + 5;
  const cpu = fresh && valid(s.cpu_percent) ? s.cpu_percent : null;
  const memory = fresh && valid(s.memory_percent) ? s.memory_percent : null;
  const mb = fresh && valid(s.memory_usage_mb) ? s.memory_usage_mb : null;
  const peak = cpu == null && memory == null ? null : Math.max(cpu ?? 0, memory ?? 0);
  const level = s.status !== 'running' ? 'off' : pressure(peak);
  const speed = peak == null || peak < 10 ? 0 : peak < 30 ? 2.8 : peak < 60 ? 1.8 : peak < 85 ? 1 : .55;
  return { cpu, memory, mb, peak, level, speed };
}

export function podResources(list: Service[], now = Date.now()) {
  const running = list.filter(s => s.status === 'running');
  const samples = running.map(s => serviceResources(s, now));
  const sum = (key: 'cpu' | 'mb') => samples.length && samples.every(s => s[key] != null)
    ? samples.reduce((n, s) => n + s[key]!, 0) : null;
  const maximum = (key: 'cpu' | 'memory') => {
    const numbers = samples.map(s => s[key]).filter(valid);
    return numbers.length ? Math.max(...numbers) : null;
  };
  const cpuPeak = maximum('cpu'), memoryPeak = maximum('memory');
  const peak = cpuPeak == null && memoryPeak == null ? null : Math.max(cpuPeak ?? 0, memoryPeak ?? 0);
  const partial = samples.some(s => s.cpu == null || s.memory == null);
  const level: Pressure = !running.length ? 'off' : pressure(peak);
  return { cpu: sum('cpu'), mb: sum('mb'), cpuPeak, memoryPeak, peak, level, partial,
    busy: level === 'warm' || level === 'hot', measured: samples.some(s => s.peak != null) };
}

export function memoryLabel(mb: number | null) {
  return mb == null ? '—' : mb >= 1024 ? `${(mb / 1024).toFixed(1)} GiB` : `${Math.round(mb)} MiB`;
}
export const percentLabel = (n: number | null) => n == null ? '—' : `${n < 10 ? n.toFixed(1) : Math.round(n)}%`;
export const podLabel = (name: string) => /^[a-f0-9]{32,64}$/i.test(name)
  ? `Pod ${name.slice(0, 8)}` : name.replace(/-pod$/, '');
