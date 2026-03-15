import { json } from "../lib/response";

export function handleStripe(): Response {
  return json(
    { error: "Stripe webhook not implemented yet" },
    501,
  );
}
