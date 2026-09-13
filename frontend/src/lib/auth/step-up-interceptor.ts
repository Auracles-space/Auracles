/**
 * Browser-side response interceptor for step-up 2FA (403 `step_up_required`).
 *
 * When a sensitive endpoint refuses because the user's step-up window is
 * closed, this interceptor opens the global step-up prompt, waits for the
 * user to verify a code, and replays the original request once. The replay
 * is rebuilt from the request URL, method, headers and the already
 * serialized `options.body` rather than `request.clone()`, because `fetch`
 * has consumed the original body by the time a response interceptor runs.
 *
 * `totp_setup_required` (2FA not enrolled) is not prompted: the user is sent
 * to security settings through the incomplete-user event instead.
 *
 * SSR-safe: install is a no-op outside the browser. The core is dependency-
 * injected so it can be unit-tested without the live client.
 *
 * Maps to: docs/superpowers/specs/2026-09-13-step-up-and-admin-console-design.md §3.
 */
import { client } from "@/lib/generated/sdk.gen";

import {
  buildIncompleteUserDetail,
  INCOMPLETE_USER_EVENT,
  type IncompleteUserEventDetail,
} from "./incomplete-user-events";
import {
  parseStepUpErrorCode,
  parseStepUpOnboardingUrl,
  requestStepUp,
} from "./step-up-gate";
import { authTokenStore } from "./token-store";

/** The step-up endpoint's own 403 must never re-prompt. */
const NO_PROMPT_PATHS = ["/v1/auth/step-up"];

/** Dependencies the 403 recovery core needs, injected for testability. */
type StepUpRetryDeps = {
  requestStepUp: () => Promise<boolean>;
  getToken: () => string | null;
  fetchImpl: typeof fetch;
  onSetupRequired: (onboardingUrl: string) => void;
};

/** The subset of hey-api request options the replay needs. */
type ReplayOptions = {
  body?: unknown;
};

/**
 * Recover a single step-up 403 by prompting once and replaying the request.
 *
 * @param response - The response returned for the original request.
 * @param request - The original request (its body is already consumed).
 * @param options - hey-api options; `body` is the serialized payload.
 * @param deps - Prompt, token accessor, fetch, and setup-required handler.
 * @returns The replayed response on success, else the original.
 */
export async function retryWithStepUpOn403(
  response: Response,
  request: Request,
  options: ReplayOptions,
  deps: StepUpRetryDeps,
): Promise<Response> {
  if (response.status !== 403) {
    return response;
  }
  if (NO_PROMPT_PATHS.some((path) => request.url.includes(path))) {
    return response;
  }

  let parsed: unknown = null;
  try {
    parsed = await response.clone().json();
  } catch {
    return response;
  }
  const code = parseStepUpErrorCode(parsed);
  if (code === null) {
    return response;
  }
  if (code === "totp_setup_required") {
    deps.onSetupRequired(parseStepUpOnboardingUrl(parsed) ?? "/settings/security");
    return response;
  }

  const verified = await deps.requestStepUp();
  if (!verified) {
    return response;
  }

  const headers = new Headers(request.headers);
  const token = deps.getToken();
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  const body =
    request.method === "GET" || request.method === "HEAD"
      ? undefined
      : (options.body as BodyInit | undefined);
  try {
    const replay = new Request(request.url, {
      method: request.method,
      headers,
      body,
      credentials: request.credentials,
      redirect: request.redirect,
    });
    return await deps.fetchImpl(replay);
  } catch {
    return response;
  }
}

let installed = false;

/**
 * Install the step-up interceptor exactly once per process.
 *
 * Safe to call from `configureBrowserClient` on every render; subsequent
 * calls are no-ops. Skipped during SSR (`window` undefined).
 */
export function installStepUpInterceptor(): void {
  if (installed || typeof window === "undefined") {
    return;
  }
  installed = true;
  client.interceptors.response.use((response, request, options) =>
    retryWithStepUpOn403(response, request, options as ReplayOptions, {
      requestStepUp,
      getToken: () => authTokenStore.getState().accessToken,
      fetchImpl: (input: RequestInfo | URL, init?: RequestInit) =>
        fetch(input, init),
      onSetupRequired: (onboardingUrl) => {
        const attemptedPath = `${window.location.pathname}${window.location.search}`;
        const detail = buildIncompleteUserDetail(
          { error_code: "totp_setup_required", onboarding_url: onboardingUrl },
          attemptedPath,
        );
        if (!detail) {
          return;
        }
        window.dispatchEvent(
          new CustomEvent<IncompleteUserEventDetail>(INCOMPLETE_USER_EVENT, {
            detail,
          }),
        );
      },
    }),
  );
}
