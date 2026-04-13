import { motion } from 'framer-motion';
import type { ReactNode } from 'react';
import type { VibrationParams } from '../../types';

interface Props {
  params: VibrationParams;
  children: ReactNode;
}

export function VibrationWrapper({ params, children }: Props) {
  if (params.intensity === 'calm' || params.duration === 0) {
    return <>{children}</>;
  }

  return (
    <motion.div
      animate={{ x: params.x, y: params.y }}
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
