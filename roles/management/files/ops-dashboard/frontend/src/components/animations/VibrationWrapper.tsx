import { motion } from 'framer-motion';
import { useMemo } from 'react';
import type { ReactNode } from 'react';
import type { VibrationParams } from '../../types';

interface Props {
  params: VibrationParams;
  children: ReactNode;
}

// Module-level reduced-motion detection — safe for SSR because we default to false.
const prefersReducedMotion =
  typeof window !== 'undefined' &&
  typeof window.matchMedia === 'function' &&
  window.matchMedia('(prefers-reduced-motion: reduce)').matches;

// Scale a vibration array: clamp peak to `cap` and multiply all values by 0.4.
function scaleAmplitude(values: number[], scale = 0.4, cap = 2): number[] {
  return values.map((v) => {
    const scaled = v * scale;
    if (scaled > cap) return cap;
    if (scaled < -cap) return -cap;
    return scaled;
  });
}

export function VibrationWrapper({ params, children }: Props) {
  const scaled = useMemo(() => {
    if (prefersReducedMotion) {
      return { x: [0], y: [0] };
    }
    return {
      x: scaleAmplitude(params.x),
      y: scaleAmplitude(params.y),
    };
  }, [params.x, params.y]);

  if (prefersReducedMotion || params.intensity === 'calm' || params.duration === 0) {
    return <>{children}</>;
  }

  return (
    <motion.div
      animate={{ x: scaled.x, y: scaled.y }}
      transition={{
        duration: params.duration,
        repeat: Infinity,
        repeatType: 'mirror',
        ease: 'easeInOut',
      }}
    >
      {children}
    </motion.div>
  );
}
