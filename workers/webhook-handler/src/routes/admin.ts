import type { Env } from "../types/env";
import { moveUser } from "../lib/authentik";
import { json, error } from "../lib/response";

interface TierChangeRequest {
  email: string;
  from_group?: string;
  to_group?: string;
}

function authenticate(request: Request, env: Env): boolean {
  return request.headers.get("X-Admin-Key") === env.ADMIN_API_KEY;
}

export async function handleUpgrade(request: Request, env: Env): Promise<Response> {
  if (!authenticate(request, env)) {
    return error("Unauthorized", 401);
  }

  let body: TierChangeRequest;
  try {
    body = await request.json();
  } catch {
    return error("Invalid JSON body");
  }

  if (!body.email) {
    return error("Missing required field: email");
  }

  const fromGroup = body.from_group ?? "free_users";
  const toGroup = body.to_group ?? "paid_users";

  try {
    const result = await moveUser(env, body.email, fromGroup, toGroup);
    return json({ success: true, ...result });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    return error(message, 502);
  }
}

export async function handleDowngrade(request: Request, env: Env): Promise<Response> {
  if (!authenticate(request, env)) {
    return error("Unauthorized", 401);
  }

  let body: TierChangeRequest;
  try {
    body = await request.json();
  } catch {
    return error("Invalid JSON body");
  }

  if (!body.email) {
    return error("Missing required field: email");
  }

  const fromGroup = body.from_group ?? "paid_users";
  const toGroup = body.to_group ?? "free_users";

  try {
    const result = await moveUser(env, body.email, fromGroup, toGroup);
    return json({ success: true, ...result });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    return error(message, 502);
  }
}
