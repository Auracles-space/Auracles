import { describe, expect, it } from "vitest";

import {
  getOnboardingDestination,
  isPhaseOneOnboardingComplete,
} from "@/lib/auth/onboarding";

const baseUser = {
  avatar_url: null,
  deactivated_at: null,
  display_name: "Ada Markets",
  email: "ada@example.com",
  email_verified: true,
  id: "00000000-0000-4000-8000-000000000001",
  kyc_status: "verified",
  pending_roles: [],
  roles: ["operator"],
};

describe("phase one onboarding", () => {
  it("is complete when account identity is verified and KYC is submitted or verified", () => {
    expect(isPhaseOneOnboardingComplete(baseUser)).toBe(true);
    expect(
      isPhaseOneOnboardingComplete({ ...baseUser, kyc_status: "pending" }),
    ).toBe(true);
  });

  it("is incomplete when KYC has not been started", () => {
    expect(
      isPhaseOneOnboardingComplete({ ...baseUser, kyc_status: "unverified" }),
    ).toBe(false);
  });

  it("routes incomplete users to onboarding before role landing", () => {
    expect(
      getOnboardingDestination(
        { ...baseUser, kyc_status: "unverified" },
        "/explore",
      ),
    ).toBe("/settings/onboarding");
  });
});
