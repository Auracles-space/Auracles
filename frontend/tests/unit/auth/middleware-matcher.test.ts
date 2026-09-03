/**
 * Invariants tying the middleware matcher to the route guards it runs.
 *
 * Next.js picks exactly one middleware file and silently ignores any other,
 * and a guard whose path is absent from the matcher never executes. Both
 * failures are invisible: the app builds, deploys, and serves the route
 * unguarded. These tests make either one fail in CI instead.
 */
import { readdirSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { resolveAuthRouteDecision } from "@/lib/auth/route-guards";
import { config } from "@/middleware";

const FRONTEND_ROOT = resolve(__dirname, "../../..");

/** True when the matcher routes `pathname` through the middleware. */
function isMatched(pathname: string): boolean {
  return config.matcher.some(
    (pattern) =>
      pattern === pathname ||
      pattern === `${pathname}/:path*` ||
      (pattern.endsWith("/:path*") &&
        pathname.startsWith(pattern.slice(0, -"/:path*".length) + "/")),
  );
}

describe("middleware file resolution", () => {
  it("defines the middleware exactly once", () => {
    /**
     * Next.js resolves `src/middleware.ts` and ignores a sibling at the
     * project root without warning, so a stale copy looks live while
     * contributing nothing. One shipped for a month listing routes that were
     * never actually gated.
     */
    const locations = [FRONTEND_ROOT, resolve(FRONTEND_ROOT, "src")].filter(
      (dir) =>
        readdirSync(dir).some((entry) =>
          /^middleware\.(ts|js|tsx)$/.test(entry),
        ),
    );

    expect(locations).toHaveLength(1);
  });
});

describe("every redirecting guard is reachable from the matcher", () => {
  // Mirrors protectedPathPrefixes in route-guards.ts. Adding a prefix there
  // means adding it here and to the middleware matcher — this list exists so
  // that forgetting the matcher fails a test rather than silently unguarding
  // the route in production.
  const protectedPaths = [
    "/2fa-setup",
    "/admin",
    "/attestations",
    "/attestor",
    "/checkout",
    "/dashboard",
    "/dashboard/developer",
    "/dashboard/organizations",
    "/library",
    "/projects",
    "/settings",
  ];

  it.each(protectedPaths)(
    "%s redirects an anonymous visitor and is matched",
    (pathname) => {
      const decision = resolveAuthRouteDecision({ hint: null, pathname });

      expect(decision.kind).toBe("redirect");
      expect(isMatched(pathname)).toBe(true);
    },
  );

  // Signed-in users are bounced off the entry pages to their landing route.
  it.each(["/login", "/register"])(
    "%s redirects an authenticated visitor and is matched",
    (pathname) => {
      const decision = resolveAuthRouteDecision({
        hint: { userId: "u1", roles: ["operator"], twoFactorPending: false },
        pathname,
      });

      expect(decision.kind).toBe("redirect");
      expect(isMatched(pathname)).toBe(true);
    },
  );
});
