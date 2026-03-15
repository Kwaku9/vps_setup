export interface Env {
  // Vars (wrangler.toml [vars])
  AUTHENTIK_URL: string;

  // Secrets (wrangler secret put)
  AUTHENTIK_TOKEN: string;
  ADMIN_API_KEY: string;
}
