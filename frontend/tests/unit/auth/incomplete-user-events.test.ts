import { describe, expect, it } from "vitest";

import { buildIncompleteUserDetail } from "@/lib/auth/incomplete-user-events";

describe("incomplete-user event parsing", () => {
  it("builds event detail from nested backend 403 payloads", () => {
    const detail = buildIncompleteUserDetail(
      {
        detail: {
          error_code: "kyc_required",
          onboarding_url: "/settings/onboarding",
        },
      },
      "/dashboard/frameworks/new",
    );

    expect(detail).toEqual({
      attemptedPath: "/dashboard/frameworks/new",
      errorCode: "kyc_required",
      onboardingUrl: "/settings/onboarding",
    });
  });

  it("builds event detail from flat backend 403 payloads", () => {
    const detail = buildIncompleteUserDetail(
      {
        error_code: "profile_required",
        onboarding_url: "/settings/onboarding",
      },
      "/dashboard/library",
    );

    expect(detail).toEqual({
      attemptedPath: "/dashboard/library",
      errorCode: "profile_required",
      onboardingUrl: "/settings/onboarding",
    });
  });

  it("ignores unknown incomplete-user error codes", () => {
    const detail = buildIncompleteUserDetail(
      {
        error_code: "surprise_required",
        onboarding_url: "/settings/onboarding",
      },
      "/dashboard/frameworks/new",
    );

    expect(detail).toBeNull();
  });
});
