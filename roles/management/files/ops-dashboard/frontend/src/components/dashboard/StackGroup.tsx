import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import type { Service } from '../../types';
import { ServiceCard } from './ServiceCard';

interface Props {
  title: string;
  services: Service[];
  defaultOpen?: boolean;
}

export function StackGroup({ title, services, defaultOpen = true }: Props) {
  const [open, setOpen] = useState(defaultOpen);
  const runningCount = services.filter((s) => s.status === 'running').length;

  return (
    <div className="border border-gray-800 rounded-lg overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-2 px-4 py-2.5 bg-gray-800/60 hover:bg-gray-800/80
          text-left transition-colors"
      >
        <span
          className={`text-xs text-gray-400 transition-transform duration-150 ${open ? 'rotate-90' : ''}`}
        >
          &#9654;
        </span>
        <span className="text-sm font-bold text-blue-400">{title}</span>
        <span className="text-xs text-gray-500 ml-1">
          ({services.length} services{runningCount > 0 ? `, ${runningCount} running` : ''})
        </span>
      </button>
      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div className="flex flex-col gap-1 p-2">
              {services.map((svc) => (
                <ServiceCard key={svc.name} service={svc} />
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
