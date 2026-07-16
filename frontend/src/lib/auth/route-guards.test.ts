import { describe, it, expect } from "vitest";

import { resolveAuthRouteDecision } from "./route-guards";
import type { SessionHint } from "./session-hint-cookie";

/** Build a verified session hint carrying the given active roles. */
function hintWithRoles(roles: string[]): SessionHint {
  return {
    userId: "user-1",
    roles,
    totpVerified: true,
    expiresAt: Date.now() + 60_000,
  };
}

describe("resolveAuthRouteDecision — /attestations (requestor workspace)", () => {
  it("lets a contributor into the requestor workspace", () => {
    const decision = resolveAuthRouteDecision({
      hint: hintWithRoles(["contributor"]),
      pathname: "/attestations",
    });

    expect(decision).toEqual({ kind: "next" });
  });

  it("lets an operator into the requestor workspace", () => {
    const decision = resolveAuthRouteDecision({
      hint: hintWithRoles(["operator"]),
      pathname: "/attestations",
    });

    expect(decision).toEqual({ kind: "next" });
  });

  it("redirects an attestor-only user away from the requestor workspace", () => {
    const decision = resolveAuthRouteDecision({
      hint: hintWithRoles(["attestor"]),
      pathname: "/attestations",
    });

    expect(decision.kind).toBe("redirect");
  });
});
