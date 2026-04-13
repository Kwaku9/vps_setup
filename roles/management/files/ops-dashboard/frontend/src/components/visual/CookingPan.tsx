import { motion, AnimatePresence } from 'framer-motion';
import { useMemo } from 'react';
import { useDashboard } from '../../contexts/DashboardContext';
import { computeVibration } from '../../utils/vibration';
import type { Service, Stack } from '../../types';

// Shape assignment based on platform
const shapeForPlatform = (platform: string) => {
  switch (platform) {
    case 'vps': return 'circle';
    case 'azure': return 'diamond';
    case 'host': return 'square';
    default: return 'circle';
  }
};

// Stack color map
const stackColorMap: Record<string, string> = {
  core: '#06b6d4',       // cyan
  security: '#ef4444',   // red
  auth: '#a855f7',       // purple
  'azure-ai': '#3b82f6', // blue
  monitoring: '#f59e0b', // amber
  comms: '#22c55e',      // green
  frontend: '#ec4899',   // pink
  management: '#f97316', // orange
  speech: '#14b8a6',     // teal
  trading: '#84cc16',    // lime
};

// Build a service→stack lookup from stacks data
function buildStackLookup(stacks: Stack[]): Record<string, string> {
  const lookup: Record<string, string> = {};
  for (const stack of stacks) {
    for (const tier of stack.tiers) {
      for (const svc of tier.services) {
        lookup[svc] = stack.name;
      }
    }
  }
  return lookup;
}

const colorForStack = (stackName: string | undefined): string => {
  return stackColorMap[stackName ?? ''] ?? '#06b6d4'; // default cyan for core/unmatched
};

function ServiceShape({ service, index, total, stackName }: { service: Service; index: number; total: number; stackName?: string }) {
  const { metrics } = useDashboard();
  const m = metrics[service.name];
  const cpu = m?.cpu_percent ?? 0;
  const mem = m?.memory_percent ?? 0;
  const vib = computeVibration(cpu, mem);
  const shape = shapeForPlatform(service.platform);
  const color = colorForStack(stackName);

  // Distribute shapes in an organic cluster inside the pan
  const angle = (index / total) * Math.PI * 2 + (index % 3) * 0.3;
  const radius = 30 + (index % 4) * 22 + (index % 3) * 10;
  const cx = Math.cos(angle) * radius;
  const cy = Math.sin(angle) * radius * 0.6; // squish vertically for perspective
  const size = 18 + (service.memory_mb ? Math.min(service.memory_mb / 50, 12) : 0);

  return (
    <motion.g
      initial={{ opacity: 0, y: -80, scale: 0 }}
      animate={{
        opacity: 1,
        y: 0,
        scale: 1,
        x: vib.intensity !== 'calm' ? vib.x : [0],
      }}
      exit={{ opacity: 0, scale: 0, y: 30 }}
      transition={{
        opacity: { duration: 0.4, delay: index * 0.05 },
        y: { duration: 0.6, delay: index * 0.05, type: 'spring', bounce: 0.4 },
        scale: { duration: 0.4, delay: index * 0.05 },
        x: vib.duration > 0 ? { duration: vib.duration, repeat: Infinity, repeatType: 'mirror' } : undefined,
      }}
      style={{ cursor: 'pointer' }}
    >
      <title>{`${service.name} (CPU: ${cpu.toFixed(1)}%, MEM: ${mem.toFixed(1)}%)`}</title>
      {shape === 'circle' && (
        <circle cx={cx} cy={cy} r={size / 2} fill={color} fillOpacity={0.85} stroke={color} strokeWidth={1.5}
          filter={vib.intensity === 'critical' ? 'url(#glow)' : undefined} />
      )}
      {shape === 'diamond' && (
        <rect x={cx - size / 2} y={cy - size / 2} width={size} height={size} fill={color} fillOpacity={0.85}
          stroke={color} strokeWidth={1.5} transform={`rotate(45 ${cx} ${cy})`}
          filter={vib.intensity === 'critical' ? 'url(#glow)' : undefined} />
      )}
      {shape === 'square' && (
        <rect x={cx - size / 2.5} y={cy - size / 2.5} width={size / 1.25} height={size / 1.25}
          fill={color} fillOpacity={0.85} stroke={color} strokeWidth={1.5} rx={2}
          filter={vib.intensity === 'critical' ? 'url(#glow)' : undefined} />
      )}
      <text x={cx} y={cy + 1} textAnchor="middle" dominantBaseline="central"
        fontSize={7} fill="white" fontWeight="bold" pointerEvents="none">
        {service.name.length > 6 ? service.name.slice(0, 5) : service.name}
      </text>
    </motion.g>
  );
}

const flameData = [
  { x: -60, h: 22, dur: 0.9 },
  { x: -40, h: 28, dur: 1.1 },
  { x: -20, h: 20, dur: 0.8 },
  { x: 0,   h: 30, dur: 1.0 },
  { x: 20,  h: 24, dur: 0.85 },
  { x: 40,  h: 26, dur: 1.15 },
  { x: 60,  h: 18, dur: 0.95 },
];

function Flames() {
  return (
    <g>
      {flameData.map(({ x, h, dur }, i) => (
        <motion.ellipse
          key={i}
          cx={x}
          cy={0}
          rx={10}
          ry={h / 2}
          fill={i % 2 === 0 ? '#f97316' : '#fbbf24'}
          fillOpacity={0.6}
          animate={{
            ry: [h / 2, h / 2 + 6, h / 2 - 3, h / 2 + 4, h / 2],
            cy: [0, -4, 1, -3, 0],
            fillOpacity: [0.6, 0.8, 0.5, 0.75, 0.6],
          }}
          transition={{ duration: dur, repeat: Infinity, repeatType: 'mirror', delay: i * 0.12 }}
        />
      ))}
    </g>
  );
}

export function CookingPan() {
  const { services, stacks, metrics } = useDashboard();

  const stackLookup = useMemo(() => buildStackLookup(stacks), [stacks]);

  const runningServices = services.filter((s) => {
    const m = metrics[s.name];
    const status = m?.status ?? s.status;
    return status === 'running';
  });

  return (
    <div className="flex flex-col items-center justify-center h-full">
      <svg viewBox="-160 -160 320 230" className="w-full max-w-2xl" style={{ maxHeight: '60vh' }}>
        <defs>
          <filter id="glow">
            <feGaussianBlur stdDeviation="3" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
          {/* Pan gradient */}
          <radialGradient id="panGrad" cx="50%" cy="40%">
            <stop offset="0%" stopColor="#4b5563" />
            <stop offset="100%" stopColor="#1f2937" />
          </radialGradient>
          <linearGradient id="panEdge" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#6b7280" />
            <stop offset="100%" stopColor="#374151" />
          </linearGradient>
        </defs>

        {/* Flames under the pan */}
        <g transform="translate(0, 55)">
          <Flames />
        </g>

        {/* Pan body — ellipse */}
        <ellipse cx="0" cy="0" rx="140" ry="80" fill="url(#panGrad)" stroke="url(#panEdge)" strokeWidth="3" />

        {/* Pan rim highlight */}
        <ellipse cx="0" cy="-5" rx="130" ry="72" fill="none" stroke="#9ca3af" strokeWidth="0.5" strokeDasharray="4 4" opacity="0.3" />

        {/* Handle */}
        <rect x="130" y="-8" width="30" height="16" rx="4" fill="#374151" stroke="#6b7280" strokeWidth="1.5" />

        {/* Services inside the pan */}
        <g transform="translate(0, -5)">
          <AnimatePresence>
            {runningServices.map((svc, i) => (
              <ServiceShape key={svc.name} service={svc} index={i} total={runningServices.length} stackName={stackLookup[svc.name]} />
            ))}
          </AnimatePresence>
        </g>

        {/* Empty state */}
        {runningServices.length === 0 && (
          <text x="0" y="0" textAnchor="middle" fill="#6b7280" fontSize="14">
            No services running
          </text>
        )}
      </svg>

      {/* Legend */}
      <div className="flex gap-4 mt-2 text-[10px] text-gray-500 flex-wrap justify-center">
        <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-full bg-cyan-500 inline-block" /> VPS</span>
        <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rotate-45 bg-blue-500 inline-block" /> Azure</span>
        <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-sm bg-gray-500 inline-block" /> Host</span>
        <span className="text-gray-600 ml-2">Shape vibration = live CPU/MEM load</span>
      </div>
    </div>
  );
}
