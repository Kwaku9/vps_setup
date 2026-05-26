import { AnimatePresence, motion } from 'framer-motion';
import { useState } from 'react';
import { uiSpring } from '../../lib/motion';
import { GlassPanel } from '../ui/GlassPanel';
import { ServiceCard } from './ServiceCard';
import type { Service } from '../../types';
import { useDashboard } from '../../contexts/DashboardContext';

interface Props {
  title: string;
  subtitle?: string;
  services: Service[];
  onOpenDetails?: (name: string) => void;
}

export function StackGroup({ title, subtitle, services, onOpenDetails }: Props) {
  const [open, setOpen] = useState(true);
  const { metrics } = useDashboard();
  const running = services.filter((s) => (metrics[s.name]?.status ?? s.status) === 'running').length;

  return (
    <GlassPanel as="section" className="overflow-hidden">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between px-4 py-3 text-left"
      >
        <div>
          <div className="text-[13px] font-semibold tracking-wide">{title}</div>
          {subtitle && <div className="text-[11px] text-white/50 mt-0.5">{subtitle}</div>}
        </div>
        <div className="flex items-center gap-2">
          <span className="glass rounded-full px-2 py-0.5 text-[11px] text-white/70">
            {running}/{services.length}
          </span>
          <motion.span animate={{ rotate: open ? 0 : -90 }} transition={uiSpring} className="text-white/50">▾</motion.span>
        </div>
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            key="body"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={uiSpring}
            className="px-2 pb-2"
          >
            <div className="flex flex-col gap-1.5">
              {services.map((s) => <ServiceCard key={s.name} service={s} onOpenDetails={onOpenDetails} />)}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </GlassPanel>
  );
}
