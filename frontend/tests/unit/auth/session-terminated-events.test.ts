import { describe, expect, it } from "vitest";

import { buildSessionTerminatedDetail } from "@/lib/auth/session-terminated-events";

describe("buildSessionTerminatedDetail", () => {
  it("returns detail for a deactivated-account 403 body", () => {
    expect(
      buildSessionTerminatedDetail({
        detail: { error_code: "account_deactivated", message: "Account is deactivated." },
      }),
    ).toEqual({
      errorCode: "account_deactivated",
      message: "Account is deactivated.",
    });
  });

  it("returns detail for a suspended-account 403 body", () => {
    expect(
      buildSessionTerminatedDetail({
        detail: { error_code: "account_suspended", message: "Account is suspended." },
      }),
    ).toEqual({
      errorCode: "account_suspended",
      message: "Account is suspended.",
    });
  });

  it("ignores non-terminal 403 bodies", () => {
    // Incomplete-user 403s carry a different contract and must not trigger logout.
    expect(
      buildSessionTerminatedDetail({
        detail: { error_code: "role_required", onboarding_url: "/settings/onboarding" },
      }),
    ).toBeNull();
    expect(buildSessionTerminatedDetail({ detail: "Account is deactivated." })).toBeNull();
    expect(buildSessionTerminatedDetail(null)).toBeNull();
    expect(buildSessionTerminatedDetail("forbidden")).toBeNull();
  });
});
