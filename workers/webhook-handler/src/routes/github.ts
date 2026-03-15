import { json } from "../lib/response";

export function handleGithub(): Response {
  return json(
    { error: "GitHub webhook not implemented yet" },
    501,
  );
}
