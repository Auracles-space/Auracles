/**
 * Stripe browser client loader for payment and checkout UI.
 *
 * Frontend code only receives the publishable key. Secret keys stay in the
 * backend environment and must never be exposed to Next.js client bundles.
 */
import { loadStripe, type Stripe } from "@stripe/stripe-js";

let stripeClientPromise: Promise<Stripe | null> | null = null;

/**
 * Return the configured Stripe publishable key for browser-side Elements.
 *
 * @returns Stripe publishable key from `NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY`.
 * @throws Error when the key is missing or is not a publishable key.
 */
export function getStripePublishableKey(): string {
  const key = process.env.NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY?.trim();
  if (!key) {
    throw new Error("NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY is required.");
  }
  if (!key.startsWith("pk_")) {
    throw new Error("Stripe browser code requires a publishable key.");
  }
  return key;
}

/**
 * Return a cached Stripe.js client promise for browser payment flows.
 *
 * @returns Cached promise from Stripe's official `loadStripe` helper.
 */
export function getStripeClient(): Promise<Stripe | null> {
  stripeClientPromise ??= loadStripe(getStripePublishableKey());
  return stripeClientPromise;
}
