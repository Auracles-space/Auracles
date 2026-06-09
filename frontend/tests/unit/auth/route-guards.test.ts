import { describe, expect, it } from "vitest";

import {
  getRoleLandingPath,
  resolveAuthRouteDecision,
} from "@/lib/auth/route-guards";

const futureHint = {
  expiresAt: Math.floor(Date.now() / 1000) + 3600,
  roles: ["contributor"],
  totpVerified: false,
  userId: "user-1",
};

describe("auth route guards", () => {
  it.each([
    [["admin"], "/admin"],
    [["attestor"], "/assignments"],
    [["operator"], "/explore"],
    [["contributor"], "/dashboard"],
  ])("maps %s to %s", (roles, expectedPath) => {
    expect(getRoleLandingPath(roles)).toBe(expectedPath);
  });

  it("redirects an authenticated visitor away from login", () => {
    expect(
      resolveAuthRouteDecision({ hint: futureHint, pathname: "/login" }),
    ).toEqual({ kind: "redirect", location: "/dashboard" });
  });

  it("gates protected auth routes when no session hint is present", () => {
    expect(
      resolveAuthRouteDecision({ hint: null, pathname: "/settings/kyc" }),
    ).toEqual({ kind: "redirect", location: "/login?next=%2Fsettings%2Fkyc" });
    expect(
      resolveAuthRouteDecision({
        hint: null,
        pathname: "/checkout/00000000-0000-4000-8000-000000000013",
      }),
    ).toEqual({
      kind: "redirect",
      location:
        "/login?next=%2Fcheckout%2F00000000-0000-4000-8000-000000000013",
    });
  });

  it("allows the 2FA challenge before a browser session exists", () => {
    expect(
      resolveAuthRouteDecision({ hint: null, pathname: "/2fa-challenge" }),
    ).toEqual({ kind: "next" });
  });

  it("allows the onboarding prompt before privileged settings access", () => {
    expect(
      resolveAuthRouteDecision({ hint: null, pathname: "/settings/onboarding" }),
    ).toEqual({ kind: "next" });
  });
});
