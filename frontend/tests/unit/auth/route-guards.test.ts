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
    [["contributor"], "/dashboard"],
    [["developer"], "/dashboard/developer"],
    [["operator", "contributor"], "/explore"],
  ])("maps %s to %s", (roles, expectedPath) => {
    expect(getRoleLandingPath(roles)).toBe(expectedPath);
  });

  it("lands a no-active-role user on a path they are allowed to view", () => {
    // A pending attestor has zero active roles. Their landing path must not be
    // a role-gated route, or middleware redirects it back to the same landing
    // path forever (ERR_TOO_MANY_REDIRECTS on login).
    const landing = getRoleLandingPath([]);
    const decision = resolveAuthRouteDecision({
      hint: makeHint([]),
      pathname: landing,
    });
    expect(decision).toEqual({ kind: "next" });
  });

  it("redirects an authenticated visitor away from login", () => {
    expect(
      resolveAuthRouteDecision({ hint: futureHint, pathname: "/login" }),
    ).toEqual({ kind: "redirect", location: "/dashboard" });
  });

  it.each([
    // Not self-assignable: nothing the user can do about it, so a silent
    // bounce to their own landing page is the honest outcome.
    ["/admin", ["operator"], "/explore"],
    ["/attestor", ["operator"], "/explore"],
  ])(
    "bounces %s to the landing page when holding %s and the role cannot be self-added",
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
    // Both directions: whichever marketplace role is missing, the user can add
    // it, so send them where they can — silently landing them somewhere else
    // told them nothing about why the page would not open.
    ["/dashboard/frameworks", ["operator"], "%2Fdashboard%2Fframeworks"],
    ["/dashboard/collections", ["operator"], "%2Fdashboard%2Fcollections"],
    ["/library", ["contributor"], "%2Flibrary"],
    ["/checkout/checkout-1", ["contributor"], "%2Fcheckout%2Fcheckout-1"],
    ["/attestations", ["attestor"], "%2Fattestations"],
  ])(
    "offers the missing role for %s when holding %s",
    (pathname, roles, encodedNext) => {
      expect(
        resolveAuthRouteDecision({
          hint: makeHint(roles as string[]),
          pathname,
        }),
      ).toEqual({
        kind: "redirect",
        location: `/settings/roles?next=${encodedNext}`,
      });
    },
  );

  it("does not loop: the roles page itself is always reachable", () => {
    expect(
      resolveAuthRouteDecision({
        hint: makeHint(["attestor"]),
        pathname: "/settings/roles",
      }),
    ).toEqual({ kind: "next" });
  });

  it.each([
    ["/admin", ["admin"]],
    ["/attestations", ["contributor"]],
    ["/attestations", ["operator"]],
    ["/dashboard/organizations", ["admin"]],
    ["/dashboard/organizations", ["operator"]],
    ["/dashboard/organizations/org-1", ["attestor"]],
    ["/dashboard/frameworks", ["contributor"]],
    ["/dashboard/developer", ["operator"]],
    ["/dashboard/developer", ["contributor"]],
    ["/dashboard/developer", ["developer"]],
    ["/library", ["operator"]],
    ["/projects/project-1", ["operator"]],
    ["/projects/project-1", ["contributor"]],
    ["/settings/identity", ["operator"]],
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
