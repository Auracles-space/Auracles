/**
 * Pure auth route decisions for Next.js middleware.
 *
 * Middleware cannot see the in-memory access token, so these helpers use only
 * the signed `session_hint` cookie for routing. Backend authorization still
 * depends on verified JWTs and database state on every protected API call.
 */
import type { SessionHint } from "./session-hint-cookie";

export type AuthRouteDecision =
  | { kind: "next" }
  | { kind: "redirect"; location: string };

const publicAuthPaths = new Set([
  "/forgot-password",
  "/login",
  "/register",
  "/reset-password",
  "/settings/onboarding",
  "/verify-email",
]);

const protectedPathPrefixes = [
  "/2fa-setup",
  "/admin",
  "/assignments",
  "/checkout",
  "/dashboard",
  "/settings",
];

/**
 * Select the first authenticated landing path based on role precedence.
 *
 * @param roles - Active roles from a verified session hint.
 */
export function getRoleLandingPath(roles: string[]): string {
  if (roles.includes("admin")) {
    return "/admin";
  }
  if (roles.includes("attestor")) {
    return "/assignments";
  }
  if (roles.includes("operator")) {
    return "/explore";
  }
  return "/dashboard";
}

function isProtectedPath(pathname: string): boolean {
  return protectedPathPrefixes.some((prefix) => {
    return pathname === prefix || pathname.startsWith(`${prefix}/`);
  });
}

/**
 * Resolve middleware routing without touching Next.js request objects.
 *
 * @param input - Current pathname and optional verified session hint.
 */
export function resolveAuthRouteDecision(input: {
  hint: SessionHint | null;
  pathname: string;
}): AuthRouteDecision {
  const { hint, pathname } = input;

  if (pathname === "/2fa-challenge" || pathname === "/settings/onboarding") {
    return { kind: "next" };
  }

  if (hint && (pathname === "/login" || pathname === "/register")) {
    return { kind: "redirect", location: getRoleLandingPath(hint.roles) };
  }

  if (!hint && isProtectedPath(pathname)) {
    return {
      kind: "redirect",
      location: `/login?next=${encodeURIComponent(pathname)}`,
    };
  }

  if (!hint && publicAuthPaths.has(pathname)) {
    return { kind: "next" };
  }

  return { kind: "next" };
}
