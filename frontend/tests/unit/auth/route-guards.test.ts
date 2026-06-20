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

/**
 * Build a verified session-hint fixture with explicit roles.
 *
 * @param roles - Active roles to encode in the auth hint.
 */
function makeHint(roles: string[]) {
  return {
    expiresAt: Math.floor(Date.now() / 1000) + 3600,
    roles,
    totpVerified: false,
    userId: "user-1",
  };
}

describe("auth route guards", () => {
  it.each([
    [["admin"], "/admin"],
    [["attestor"], "/attestor/assignments"],
    [["operator"], "/explore"],
    [["contributor"], "/dashboard"],
    [["developer"], "/dashboard/developer"],
    [["operator", "contributor"], "/dashboard"],
  ])("maps %s to %s", (roles, expectedPath) => {
    expect(getRoleLandingPath(roles)).toBe(expectedPath);
  });

  it("redirects an authenticated visitor away from login", () => {
    expect(
      resolveAuthRouteDecision({ hint: futureHint, pathname: "/login" }),
    ).toEqual({ kind: "redirect", location: "/dashboard" });
  });

  it.each([
    ["/admin", ["operator"], "/explore"],
    ["/attestations", ["operator"], "/explore"],
    ["/dashboard/frameworks", ["operator"], "/explore"],
    ["/library", ["contributor"], "/dashboard"],
    ["/checkout/checkout-1", ["contributor"], "/dashboard"],
  ])(
    "redirects wrong-role users away from %s when holding %s",
    (pathname, roles, location) => {
      expect(
        resolveAuthRouteDecision({
          hint: makeHint(roles as string[]),
          pathname,
        }),
      ).toEqual({ kind: "redirect", location });
    },
  );

  it.each([
    ["/admin", ["admin"]],
    ["/attestations", ["attestor"]],
    ["/dashboard/frameworks", ["contributor"]],
    ["/dashboard/developer", ["operator"]],
    ["/dashboard/developer", ["contributor"]],
    ["/dashboard/developer", ["developer"]],
    ["/library", ["operator"]],
    ["/projects/project-1", ["operator"]],
    ["/projects/project-1", ["contributor"]],
    ["/settings/profile", ["operator"]],
  ])("allows the right roles through for %s", (pathname, roles) => {
    expect(
      resolveAuthRouteDecision({
        hint: makeHint(roles as string[]),
        pathname,
      }),
    ).toEqual({ kind: "next" });
  });

  it("treats operator+contributor as a union across protected workspaces", () => {
    const hint = makeHint(["operator", "contributor"]);

    expect(
      resolveAuthRouteDecision({
        hint,
        pathname: "/projects",
      }),
    ).toEqual({ kind: "next" });
    expect(
      resolveAuthRouteDecision({
        hint,
        pathname: "/dashboard/financials",
      }),
    ).toEqual({ kind: "next" });
    expect(
      resolveAuthRouteDecision({
        hint,
        pathname: "/library",
      }),
    ).toEqual({ kind: "next" });
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
    expect(
      resolveAuthRouteDecision({ hint: null, pathname: "/projects" }),
    ).toEqual({ kind: "redirect", location: "/login?next=%2Fprojects" });
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

  it("never blocks public marketplace paths", () => {
    expect(
      resolveAuthRouteDecision({ hint: null, pathname: "/explore" }),
    ).toEqual({ kind: "next" });
    expect(
      resolveAuthRouteDecision({
        hint: makeHint(["operator"]),
        pathname: "/explore/framework-1",
      }),
    ).toEqual({ kind: "next" });
  });
});
