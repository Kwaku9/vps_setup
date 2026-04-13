import type { VibrationParams } from '../types';

export function computeVibration(cpuPercent: number, memPercent: number): VibrationParams {
  const load = Math.max(cpuPercent, memPercent);

  if (load < 10)
    return { x: [0], y: [0], duration: 0, intensity: 'calm' };
  if (load < 30)
    return { x: [-0.3, 0.3, 0], y: [-0.2, 0.2, 0], duration: 2, intensity: 'moderate' };
  if (load < 60)
    return { x: [-0.8, 0.8, -0.5, 0.5, 0], y: [-0.5, 0.5, 0], duration: 1, intensity: 'active' };
  if (load < 85)
    return { x: [-1.5, 1.5, -1, 1, 0], y: [-1, 1, -0.5, 0.5, 0], duration: 0.5, intensity: 'stressed' };
  return {
    x: [-3, 3, -2, 2, -1, 1, 0],
    y: [-2, 2, -1.5, 1.5, 0],
    duration: 0.3,
    intensity: 'critical',
  };
}

export const intensityColors: Record<string, string> = {
  calm: 'border-gray-600',
  moderate: 'border-green-500/50',
  active: 'border-yellow-500/50',
  stressed: 'border-orange-500/70',
  critical: 'border-red-500',
};

export const intensityGlow: Record<string, string> = {
  calm: '',
  moderate: 'shadow-green-500/10',
  active: 'shadow-yellow-500/20',
  stressed: 'shadow-orange-500/30',
  critical: 'shadow-red-500/50 shadow-lg',
};
