import { describe, expect, it } from "vitest";

import {
  getOnboardingDestination,
  isPhaseOneOnboardingComplete,
  toSafeInternalPath,
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

describe("toSafeInternalPath", () => {
  it("keeps an ordinary same-origin path", () => {
    expect(toSafeInternalPath("/projects/new")).toBe("/projects/new");
    expect(toSafeInternalPath("/explore?q=risk")).toBe("/explore?q=risk");
  });

  it("rejects anything that could leave the origin", () => {
    // The value arrives from a query parameter, so it is attacker-controlled:
    // onboarding must never bounce a signed-in user off-site.
    expect(toSafeInternalPath("https://evil.example/steal")).toBeNull();
    expect(toSafeInternalPath("//evil.example/steal")).toBeNull();
    expect(toSafeInternalPath("/\\evil.example/steal")).toBeNull();
    expect(toSafeInternalPath("javascript:alert(1)")).toBeNull();
  });

  it("treats a missing or empty value as no destination", () => {
    expect(toSafeInternalPath(undefined)).toBeNull();
    expect(toSafeInternalPath("")).toBeNull();
  });
});
