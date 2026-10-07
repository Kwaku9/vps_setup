import { api } from './api';
import type { Me, Role } from './types';

const RANK: Record<Role, number> = { viewer: 1, operator: 2, admin: 3 };

export const user = $state<{ me: Me | null }>({ me: null });

export async function loadMe() {
  try { user.me = await api.me(); } catch { /* 401 already redirects to sign-in */ }
}

/** Mirrors the server's require_role(): the server still decides. */
export const can = (min: Role) => !!user.me && RANK[user.me.role] >= RANK[min];
