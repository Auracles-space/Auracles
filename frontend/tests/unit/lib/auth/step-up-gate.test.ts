import { beforeEach, describe, expect, it } from "vitest";

import {
  parseStepUpErrorCode,
  requestStepUp,
  resetStepUpGate,
  settleStepUp,
  stepUpStore,
} from "@/lib/auth/step-up-gate";

describe("step-up gate", () => {
  beforeEach(() => {
    resetStepUpGate();
  });

  it("marks a prompt pending and resolves true when settled with a window", async () => {
    const promise = requestStepUp();

    expect(stepUpStore.getState().pending).toBe(true);
    settleStepUp(true, Date.now() + 600_000);

    await expect(promise).resolves.toBe(true);
    expect(stepUpStore.getState().pending).toBe(false);
    expect(stepUpStore.getState().verifiedUntil).toBeGreaterThan(Date.now());
  });

  it("shares one prompt across concurrent requests", async () => {
    const first = requestStepUp();
    const second = requestStepUp();
    settleStepUp(true, Date.now() + 600_000);

    await expect(Promise.all([first, second])).resolves.toEqual([true, true]);
  });

  it("resolves false and keeps no window when cancelled", async () => {
    const promise = requestStepUp();
    settleStepUp(false);

    await expect(promise).resolves.toBe(false);
    expect(stepUpStore.getState().verifiedUntil).toBeNull();
  });

  it("parses the two step-up error codes from a 403 body and ignores others", () => {
    expect(parseStepUpErrorCode({ detail: { error_code: "step_up_required" } })).toBe(
      "step_up_required",
    );
    expect(
      parseStepUpErrorCode({
        detail: { error_code: "totp_setup_required", onboarding_url: "/2fa-setup" },
      }),
    ).toBe("totp_setup_required");
    expect(parseStepUpErrorCode({ detail: { error_code: "role_required" } })).toBeNull();
    expect(parseStepUpErrorCode({ detail: "Forbidden" })).toBeNull();
    expect(parseStepUpErrorCode(null)).toBeNull();
  });
});
