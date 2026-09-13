/**
 * Step-up 2FA gate: shared state between the API interceptor and the dialog.
 *
 * Sensitive endpoints answer 403 `step_up_required` until the user verifies
 * a code once (`POST /v1/auth/step-up`), which opens a 10-minute window on
 * the backend. The interceptor asks this gate for a prompt and awaits the
 * result; the global `StepUpDialog` renders while a prompt is pending and
 * settles it. Concurrent 403s share one prompt so the user is asked once.
 *
 * Maps to: docs/superpowers/specs/2026-09-13-step-up-and-admin-console-design.md §3.
 */
import { createStore } from "zustand/vanilla";

export type StepUpErrorCode = "step_up_required" | "totp_setup_required";

export type StepUpState = {
  /** A prompt is waiting for the user to verify or cancel. */
  pending: boolean;
  /** Epoch milliseconds when the current window closes, or null if none. */
  verifiedUntil: number | null;
};

const initialState: StepUpState = { pending: false, verifiedUntil: null };

export const stepUpStore = createStore<StepUpState>(() => initialState);

let inflight: {
  promise: Promise<boolean>;
  resolve: (ok: boolean) => void;
} | null = null;

/**
 * Ask for a step-up prompt and resolve once the user verifies (true) or
 * cancels (false). A second call while a prompt is pending joins it.
 */
export function requestStepUp(): Promise<boolean> {
  if (inflight) {
    return inflight.promise;
  }
  let resolve: (ok: boolean) => void = () => {};
  const promise = new Promise<boolean>((done) => {
    resolve = done;
  });
  inflight = { promise, resolve };
  stepUpStore.setState({ pending: true });
  return promise;
}

/**
 * Settle the pending prompt.
 *
 * @param ok - Whether verification succeeded.
 * @param verifiedUntil - Epoch milliseconds when the new window closes.
 */
export function settleStepUp(ok: boolean, verifiedUntil?: number): void {
  const current = inflight;
  inflight = null;
  stepUpStore.setState({
    pending: false,
    verifiedUntil: ok ? (verifiedUntil ?? null) : stepUpStore.getState().verifiedUntil,
  });
  current?.resolve(ok);
}

/**
 * Record a window learned from `GET /v1/auth/step-up` without a prompt.
 *
 * @param verifiedUntil - Epoch milliseconds, or null when no window is open.
 */
export function setStepUpVerifiedUntil(verifiedUntil: number | null): void {
  stepUpStore.setState({ verifiedUntil });
}

/** Clear all gate state (tests, logout). */
export function resetStepUpGate(): void {
  inflight?.resolve(false);
  inflight = null;
  stepUpStore.setState(initialState);
}

/**
 * Read the step-up error code from a parsed 403 body, if it carries one.
 *
 * @param body - Parsed JSON body of a 403 response.
 */
export function parseStepUpErrorCode(body: unknown): StepUpErrorCode | null {
  if (!body || typeof body !== "object") {
    return null;
  }
  const root = body as Record<string, unknown>;
  const detail =
    root.detail && typeof root.detail === "object"
      ? (root.detail as Record<string, unknown>)
      : root;
  const code = detail.error_code;
  if (code === "step_up_required" || code === "totp_setup_required") {
    return code;
  }
  return null;
}

/**
 * Read the onboarding URL from a `totp_setup_required` 403 body.
 *
 * @param body - Parsed JSON body of a 403 response.
 */
export function parseStepUpOnboardingUrl(body: unknown): string | null {
  if (!body || typeof body !== "object") {
    return null;
  }
  const root = body as Record<string, unknown>;
  const detail =
    root.detail && typeof root.detail === "object"
      ? (root.detail as Record<string, unknown>)
      : root;
  return typeof detail.onboarding_url === "string" ? detail.onboarding_url : null;
}
