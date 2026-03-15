import { json } from "../lib/response";

export function handleHealth(): Response {
  return json({ status: "ok", service: "webhook-handler" });
}
