import type { ElementType, HTMLAttributes, ReactNode } from 'react';

interface Props extends HTMLAttributes<HTMLDivElement> {
  as?: 'div' | 'section' | 'aside' | 'header' | 'nav';
  tone?: 'default' | 'large';
  children: ReactNode;
}

export function GlassPanel({ as = 'div', tone = 'default', className = '', children, ...rest }: Props) {
  const Tag = as as ElementType;
  const toneCls = tone === 'large' ? 'glass glass-lg' : 'glass';
  return (
    <Tag className={`${toneCls} rounded-[var(--r-lg)] ${className}`} {...rest}>
      {children}
    </Tag>
  );
}
