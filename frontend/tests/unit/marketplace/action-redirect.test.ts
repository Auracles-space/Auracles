import { describe, expect, it } from "vitest";

import {
  MARKETPLACE_ONBOARDING_ERROR_CODES,
  resolveMarketplaceActionRedirect,
} from "@/lib/marketplace/action-redirect";

describe("marketplace action redirect handling", () => {
  it("routes onboarding-gated marketplace actions to onboarding with the current intent preserved", () => {
    const redirect = resolveMarketplaceActionRedirect({
      error: { detail: "KYC required.", error_code: "kyc_required" },
      pathname: "/dashboard/frameworks/new",
    });

    expect(MARKETPLACE_ONBOARDING_ERROR_CODES).toContain("kyc_required");
    expect(redirect).toBe(
      "/settings/onboarding?next=%2Fdashboard%2Fframeworks%2Fnew",
    );
  });

  it("ignores ordinary API errors so read-only marketplace pages keep rendering", () => {
    const redirect = resolveMarketplaceActionRedirect({
      error: { detail: "Framework not found." },
      pathname: "/explore/fw_123",
    });

    expect(redirect).toBeNull();
  });
});
