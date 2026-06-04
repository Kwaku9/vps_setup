import { useMemo } from 'react';
import type { TimeseriesPoint } from '../../types';

interface Props {
  points: TimeseriesPoint[];
  width?: number;
  height?: number;
  baselineColor?: string;
  responsive?: boolean;
}

function pickColor(latest: number, baseline: string): string {
  if (latest > 80) return '#ff453a';   // status-red
  if (latest > 50) return '#ffd60a';   // status-yellow
  return baseline;
}

export function Sparkline({
  points,
  width = 60,
  height = 16,
  baselineColor = '#64d2ff', // vps-cyan
  responsive = false,
}: Props) {
  const { d, latest, color } = useMemo(() => {
    if (points.length < 2) return { d: '', latest: 0, color: baselineColor };
    const values = points.map((p) => p[1]);
    const minV = 0;                                  // anchored to 0 so heights are comparable
    const maxV = Math.max(100, ...values);           // anchored to 100% so a calm container shows flat
    const range = maxV - minV || 1;
    const step = width / (points.length - 1);
    const path = points
      .map((p, i) => {
        const x = i * step;
        const y = height - ((p[1] - minV) / range) * height;
        return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`;
      })
      .join(' ');
    const last = values[values.length - 1];
    return { d: path, latest: last, color: pickColor(last, baselineColor) };
  }, [points, width, height, baselineColor]);

  if (!d) {
    return <div className="inline-block" style={{ width: responsive ? '100%' : width, height }} aria-hidden />;
  }

  return (
    <svg
      width={responsive ? '100%' : width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      aria-label={`sparkline latest ${latest.toFixed(1)}`}
    >
      <path d={d} fill="none" stroke={color} strokeWidth={1.25} strokeLinecap="round" strokeLinejoin="round" opacity={0.95} />
    </svg>
  );
}
