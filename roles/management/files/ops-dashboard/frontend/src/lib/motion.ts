// frontend/src/lib/motion.ts
import type { Transition } from 'framer-motion';

export const uiSpring: Transition = { type: 'spring', stiffness: 320, damping: 32 };
export const pop:      Transition = { type: 'spring', stiffness: 560, damping: 28 };
export const fadeRise = {
  initial: { opacity: 0, y: 4 },
  animate: { opacity: 1, y: 0 },
  transition: uiSpring,
};
