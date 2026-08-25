export type CollapseDirection = 'left' | 'right' | 'up';

export interface PanelToggleState {
  collapsed: boolean;
  toggle(): void;
}

/**
 * Makes a panel retractable by wrapping it in a flex container with a toggle button.
 * Returns the wrapper (to be appended to DOM instead of the original container)
 * and a toggle function for keyboard shortcuts.
 */
export function makeRetractable(
  container: HTMLDivElement,
  direction: CollapseDirection,
  persistKey?: string
): { wrapper: HTMLDivElement; state: PanelToggleState } {
  const chars = getChars(direction);

  // Wrapper holds toggle + content side by side
  const wrapper = document.createElement('div');
  wrapper.classList.add('wv-hud-panel');   // targeted by cinematic hide-all
  Object.assign(wrapper.style, {
    position: 'absolute',
    display: 'flex',
    pointerEvents: 'none',
    zIndex: '1000',
  });

  // Copy positioning from container to wrapper
  copyPosition(container, wrapper, direction);

  // Reset container positioning (wrapper handles it now)
  container.style.position = 'relative';
  container.style.top = '';
  container.style.bottom = '';
  container.style.left = '';
  container.style.right = '';
  container.style.pointerEvents = 'auto';
  container.style.transition = 'transform 200ms ease-in-out, opacity 200ms ease-in-out';

  // Toggle button
  const btn = document.createElement('button');
  btn.textContent = chars[0];
  Object.assign(btn.style, {
    background: 'rgba(0, 0, 0, 0.75)',
    border: '1px solid #1a3a1a',
    color: '#33ff33',
    fontFamily: 'Courier New, monospace',
    fontSize: '11px',
    width: '18px',
    height: '18px',
    cursor: 'pointer',
    borderRadius: '2px',
    padding: '0',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    pointerEvents: 'auto',
    flexShrink: '0',
    lineHeight: '1',
  });
  btn.addEventListener('mouseenter', () => { btn.style.background = 'rgba(0, 80, 0, 0.7)'; });
  btn.addEventListener('mouseleave', () => { btn.style.background = 'rgba(0, 0, 0, 0.75)'; });

  // Arrange based on direction
  if (direction === 'left') {
    wrapper.style.flexDirection = 'row';
    wrapper.style.alignItems = 'flex-start';
    wrapper.appendChild(container);
    wrapper.appendChild(btn);
    btn.style.marginLeft = '4px';
    btn.style.marginTop = '4px';
  } else if (direction === 'right') {
    wrapper.style.flexDirection = 'row';
    wrapper.style.alignItems = 'flex-start';
    wrapper.appendChild(btn);
    wrapper.appendChild(container);
    btn.style.marginRight = '4px';
    btn.style.marginTop = '4px';
  } else {
    wrapper.style.flexDirection = 'column';
    wrapper.style.alignItems = 'center';
    wrapper.appendChild(container);
    wrapper.appendChild(btn);
    btn.style.marginTop = '4px';
  }

  const apply = (collapsed: boolean) => {
    if (collapsed) {
      btn.textContent = chars[1];
      container.style.transform = getCollapseTransform(direction);
      container.style.opacity = '0';
      container.style.pointerEvents = 'none';
    } else {
      btn.textContent = chars[0];
      container.style.transform = 'none';
      container.style.opacity = '1';
      container.style.pointerEvents = 'auto';
    }
  };

  const state: PanelToggleState = {
    collapsed: false,
    toggle() {
      this.collapsed = !this.collapsed;
      apply(this.collapsed);
      if (persistKey) {
        try { localStorage.setItem(persistKey, this.collapsed ? '1' : '0'); }
        catch { /* private mode */ }
      }
    },
  };

  // Restore prior collapse state (persisted per panel across reloads).
  if (persistKey) {
    try {
      if (localStorage.getItem(persistKey) === '1') {
        state.collapsed = true;
        // Skip the 200ms slide on initial restore.
        const prev = container.style.transition;
        container.style.transition = 'none';
        apply(true);
        requestAnimationFrame(() => { container.style.transition = prev; });
      }
    } catch { /* private mode */ }
  }

  btn.addEventListener('click', () => state.toggle());

  return { wrapper, state };
}

function getChars(d: CollapseDirection): [string, string] {
  if (d === 'left') return ['\u25C0', '\u25B6'];
  if (d === 'right') return ['\u25B6', '\u25C0'];
  return ['\u25B2', '\u25BC'];
}

function getCollapseTransform(d: CollapseDirection): string {
  if (d === 'left') return 'translateX(calc(-100% - 12px))';
  if (d === 'right') return 'translateX(calc(100% + 12px))';
  return 'translateY(calc(-100% - 24px))';
}

function copyPosition(src: HTMLDivElement, dest: HTMLDivElement, direction: CollapseDirection): void {
  if (src.style.top) dest.style.top = src.style.top;
  if (src.style.bottom) dest.style.bottom = src.style.bottom;
  if (src.style.left) dest.style.left = src.style.left;
  if (src.style.right) dest.style.right = src.style.right;
  // For centered elements (locations bar)
  if (src.style.transform?.includes('translateX(-50%)')) {
    dest.style.left = '50%';
    dest.style.transform = 'translateX(-50%)';
  }
}
