import { describe, expect, it, vi } from "vitest";

import { retryWithStepUpOn403 } from "@/lib/auth/step-up-interceptor";

/**
 * Build the dependency bundle the step-up interceptor core consumes.
 */
function makeDeps(overrides: {
  requestStepUp?: () => Promise<boolean>;
  getToken?: () => string | null;
  fetchImpl?: typeof fetch;
  onSetupRequired?: (onboardingUrl: string) => void;
} = {}) {
  return {
    requestStepUp: overrides.requestStepUp ?? vi.fn(async () => true),
    getToken: overrides.getToken ?? vi.fn(() => "token"),
    fetchImpl:
      overrides.fetchImpl ??
      (vi.fn(async () => new Response(null, { status: 200 })) as unknown as typeof fetch),
    onSetupRequired: overrides.onSetupRequired ?? vi.fn(),
  };
}

function stepUpRequired(): Response {
  return new Response(
    JSON.stringify({ detail: { error_code: "step_up_required" } }),
    { status: 403, headers: { "Content-Type": "application/json" } },
  );
}

describe("retryWithStepUpOn403", () => {
  it("passes non-403 responses through untouched", async () => {
    const deps = makeDeps();
    const response = new Response(null, { status: 200 });
    const request = new Request("http://api/v1/admin/orgs/1/suspend", { method: "POST" });

    const result = await retryWithStepUpOn403(response, request, { body: undefined }, deps);

    expect(result).toBe(response);
    expect(deps.requestStepUp).not.toHaveBeenCalled();
  });

  it("passes other 403s through without prompting", async () => {
    const deps = makeDeps();
    const response = new Response(
      JSON.stringify({ detail: { error_code: "role_required", onboarding_url: "/x" } }),
      { status: 403 },
    );
    const request = new Request("http://api/v1/admin/orgs/1/suspend", { method: "POST" });

    const result = await retryWithStepUpOn403(response, request, { body: undefined }, deps);

    expect(result).toBe(response);
    expect(deps.requestStepUp).not.toHaveBeenCalled();
  });

  it("prompts for step-up and replays the original request with its body", async () => {
    const retried = new Response(JSON.stringify({ ok: true }), { status: 200 });
    const fetchImpl = vi.fn(async () => retried) as unknown as typeof fetch;
    const deps = makeDeps({ fetchImpl, getToken: () => "fresh-token" });
    const body = JSON.stringify({ verdict: "verified" });
    const request = new Request("http://api/v1/admin/orgs/1/kyb/review", {
      method: "POST",
      headers: { Authorization: "Bearer stale", "Content-Type": "application/json" },
      body,
    });

    const result = await retryWithStepUpOn403(stepUpRequired(), request, { body }, deps);

    expect(deps.requestStepUp).toHaveBeenCalledTimes(1);
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    const sent = (fetchImpl as unknown as ReturnType<typeof vi.fn>).mock.calls[0][0] as Request;
    expect(sent.method).toBe("POST");
    expect(sent.url).toBe("http://api/v1/admin/orgs/1/kyb/review");
    expect(sent.headers.get("Authorization")).toBe("Bearer fresh-token");
    expect(await sent.text()).toBe(body);
    expect(result).toBe(retried);
  });

  it("returns the original 403 when the user cancels the prompt", async () => {
    const deps = makeDeps({ requestStepUp: vi.fn(async () => false) });
    const response = stepUpRequired();
    const request = new Request("http://api/v1/admin/orgs/1/suspend", { method: "POST" });

    const result = await retryWithStepUpOn403(response, request, { body: undefined }, deps);

    expect(result).toBe(response);
    expect(deps.fetchImpl).not.toHaveBeenCalled();
  });

  it("routes an unenrolled user to security settings instead of prompting", async () => {
    const deps = makeDeps();
    const response = new Response(
      JSON.stringify({
        detail: { error_code: "totp_setup_required", onboarding_url: "/2fa-setup" },
      }),
      { status: 403 },
    );
    const request = new Request("http://api/v1/admin/orgs/1/suspend", { method: "POST" });

    const result = await retryWithStepUpOn403(response, request, { body: undefined }, deps);

    expect(result).toBe(response);
    expect(deps.onSetupRequired).toHaveBeenCalledWith("/2fa-setup");
    expect(deps.requestStepUp).not.toHaveBeenCalled();
  });

  it("never prompts for the step-up endpoint itself", async () => {
    const deps = makeDeps();
    const response = stepUpRequired();
    const request = new Request("http://api/v1/auth/step-up", { method: "POST" });

    const result = await retryWithStepUpOn403(response, request, { body: undefined }, deps);

    expect(result).toBe(response);
    expect(deps.requestStepUp).not.toHaveBeenCalled();
  });
});
