import type { Env } from "../types/env";

interface AuthentikUser {
  pk: number;
  email: string;
  username: string;
}

interface AuthentikGroup {
  pk: string;
  name: string;
}

async function api(env: Env, path: string, init?: RequestInit): Promise<Response> {
  const url = `${env.AUTHENTIK_URL}/api/v3${path}`;
  return fetch(url, {
    ...init,
    headers: {
      Authorization: `Bearer ${env.AUTHENTIK_TOKEN}`,
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });
}

export async function getUserByEmail(env: Env, email: string): Promise<AuthentikUser> {
  const res = await api(env, `/core/users/?email=${encodeURIComponent(email)}`);
  if (!res.ok) {
    throw new Error(`Authentik users API returned ${res.status}`);
  }
  const data = (await res.json()) as { results: AuthentikUser[] };
  if (data.results.length === 0) {
    throw new Error(`User not found: ${email}`);
  }
  return data.results[0];
}

export async function getGroupByName(env: Env, name: string): Promise<AuthentikGroup> {
  const res = await api(env, `/core/groups/?name=${encodeURIComponent(name)}`);
  if (!res.ok) {
    throw new Error(`Authentik groups API returned ${res.status}`);
  }
  const data = (await res.json()) as { results: AuthentikGroup[] };
  if (data.results.length === 0) {
    throw new Error(`Group not found: ${name}`);
  }
  return data.results[0];
}

export async function removeUserFromGroup(env: Env, groupPk: string, userPk: number): Promise<void> {
  const res = await api(env, `/core/groups/${groupPk}/remove_user/`, {
    method: "POST",
    body: JSON.stringify({ pk: userPk }),
  });
  // 204 = success, 404 = user wasn't in group (idempotent)
  if (!res.ok && res.status !== 404) {
    throw new Error(`Failed to remove user from group: ${res.status}`);
  }
}

export async function addUserToGroup(env: Env, groupPk: string, userPk: number): Promise<void> {
  const res = await api(env, `/core/groups/${groupPk}/add_user/`, {
    method: "POST",
    body: JSON.stringify({ pk: userPk }),
  });
  if (!res.ok) {
    throw new Error(`Failed to add user to group: ${res.status}`);
  }
}

export async function moveUser(
  env: Env,
  email: string,
  fromGroupName: string,
  toGroupName: string,
): Promise<{ user: string; from: string; to: string }> {
  const [user, fromGroup, toGroup] = await Promise.all([
    getUserByEmail(env, email),
    getGroupByName(env, fromGroupName),
    getGroupByName(env, toGroupName),
  ]);

  await removeUserFromGroup(env, fromGroup.pk, user.pk);
  await addUserToGroup(env, toGroup.pk, user.pk);

  return { user: user.email, from: fromGroupName, to: toGroupName };
}
