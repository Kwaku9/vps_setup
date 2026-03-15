import type { Env } from "./types/env";
import { handleHealth } from "./routes/health";
import { handleUpgrade, handleDowngrade } from "./routes/admin";
import { handleStripe } from "./routes/stripe";
import { handleGithub } from "./routes/github";
import { error } from "./lib/response";

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    const { pathname } = url;
    const method = request.method;

    // GET /health
    if (method === "GET" && pathname === "/health") {
      return handleHealth();
    }

    // POST /admin/upgrade-user
    if (method === "POST" && pathname === "/admin/upgrade-user") {
      return handleUpgrade(request, env);
    }

    // POST /admin/downgrade-user
    if (method === "POST" && pathname === "/admin/downgrade-user") {
      return handleDowngrade(request, env);
    }

    // POST /webhooks/stripe
    if (method === "POST" && pathname === "/webhooks/stripe") {
      return handleStripe();
    }

    // POST /webhooks/github
    if (method === "POST" && pathname === "/webhooks/github") {
      return handleGithub();
    }

    return error("Not found", 404);
  },
} satisfies ExportedHandler<Env>;
