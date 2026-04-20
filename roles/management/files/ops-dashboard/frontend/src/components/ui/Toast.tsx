import { AnimatePresence, motion } from 'framer-motion';
import { useToast } from '../../contexts/ToastContext';

const kindStyles: Record<string, string> = {
  info:    'border-sky-400/30',
  success: 'border-emerald-400/30',
  error:   'border-rose-400/30',
};

export function ToastHost() {
  const { toasts, dismiss } = useToast();
  return (
    <div className="fixed z-50 top-[max(env(safe-area-inset-top),1rem)] right-4 flex flex-col gap-2 w-[min(360px,calc(100vw-2rem))]">
      <AnimatePresence>
        {toasts.map((t) => (
          <motion.div
            key={t.id}
            initial={{ opacity: 0, y: -8, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -8, scale: 0.98 }}
            transition={{ type: 'spring', stiffness: 320, damping: 32 }}
            className={`rounded-2xl border ${kindStyles[t.kind]} px-4 py-3 text-sm
              bg-white/5 backdrop-blur-xl shadow-[0_4px_24px_rgba(0,0,0,0.45)]`}
            onClick={() => dismiss(t.id)}
          >
            <div className="font-semibold text-white">{t.title}</div>
            {t.body && <div className="text-white/70 mt-1 text-xs">{t.body}</div>}
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  );
}
