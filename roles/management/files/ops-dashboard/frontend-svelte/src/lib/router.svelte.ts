// Hash routing (#/triage, #/inventory/jobs …) so the server only ever serves
// /m/index.html and deep links survive a reload or a sign-in round trip.

export const TABS = ['triage', 'services', 'sessions', 'inventory', 'audit'] as const;
export type Tab = (typeof TABS)[number];

function parse() {
  const [tab, ...rest] = location.hash.replace(/^#\/?/, '').split('/');
  return { tab: (TABS as readonly string[]).includes(tab) ? (tab as Tab) : 'triage', rest: rest.map(decodeURIComponent) };
}

export const route = $state(parse());

addEventListener('hashchange', () => Object.assign(route, parse()));

export function go(tab: Tab, ...rest: string[]) {
  location.hash = '/' + [tab, ...rest.map(encodeURIComponent)].join('/');
}
