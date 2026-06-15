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

type RoleProtectedPrefix = {
  prefix: string;
  requiredRoles: string[] | null;
};

const publicAuthPaths = new Set([
  "/forgot-password",
  "/login",
  "/register",
  "/reset-password",
  "/settings/onboarding",
  "/verify-email",
]);

const protectedPathPrefixes: RoleProtectedPrefix[] = [
  { prefix: "/2fa-setup", requiredRoles: null },
  { prefix: "/admin", requiredRoles: ["admin"] },
  { prefix: "/attestations", requiredRoles: ["attestor"] },
  { prefix: "/attestor", requiredRoles: ["attestor"] },
  { prefix: "/checkout", requiredRoles: ["operator"] },
  { prefix: "/dashboard", requiredRoles: ["contributor"] },
  { prefix: "/library", requiredRoles: ["operator"] },
  { prefix: "/projects", requiredRoles: ["operator", "contributor"] },
  { prefix: "/settings", requiredRoles: null },
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
    return "/attestor/assignments";
  }
  if (roles.includes("operator")) {
    return "/explore";
  }
  return "/dashboard";
}

/**
 * Match a pathname against the protected-prefix map.
 *
 * @param pathname - Current request pathname.
 * @returns Matching protected prefix metadata when present.
 */
function getProtectedPrefix(pathname: string): RoleProtectedPrefix | null {
  return (
    protectedPathPrefixes.find(({ prefix }) => {
      return pathname === prefix || pathname.startsWith(`${prefix}/`);
    }) ?? null
  );
}

/**
 * Check whether the user holds at least one of the required roles.
 *
 * @param roles - Active session roles from the verified hint.
 * @param requiredRoles - Protected-route role requirement.
 */
function hasAnyRequiredRole(
  roles: string[],
  requiredRoles: string[] | null,
): boolean {
  if (!requiredRoles || requiredRoles.length === 0) {
    return true;
  }

  return requiredRoles.some((role) => roles.includes(role));
}

/**
 * Determine whether the pathname belongs to a public auth page.
 *
 * @param pathname - Current request pathname.
 */
function isPublicAuthPath(pathname: string): boolean {
  return publicAuthPaths.has(pathname);
}

/**
 * Build a login redirect that preserves the intended destination.
 *
 * @param pathname - Protected destination pathname.
 */
function loginRedirect(pathname: string): AuthRouteDecision {
  return {
    kind: "redirect",
    location: `/login?next=${encodeURIComponent(pathname)}`,
  };
}

/**
 * Build a role-landing redirect for the current session roles.
 *
 * @param roles - Active session roles from the verified hint.
 */
function landingRedirect(roles: string[]): AuthRouteDecision {
  return {
    kind: "redirect",
    location: getRoleLandingPath(roles),
  };
}

/**
 * Resolve whether the current route requires authentication and/or roles.
 *
 * @param pathname - Current request pathname.
 */
function resolveProtectedRoute(pathname: string): RoleProtectedPrefix | null {
  return getProtectedPrefix(pathname);
}

/**
 * Determine whether the route is protected by auth presence or roles.
 *
 * @param pathname - Current request pathname.
 */
function isProtectedPath(pathname: string): boolean {
  return resolveProtectedRoute(pathname) !== null;
}

/**
 * Determine whether a wrong-role redirect should apply.
 *
 * @param pathname - Current request pathname.
 * @param roles - Active session roles from the verified hint.
 */
function requiresWrongRoleRedirect(pathname: string, roles: string[]): boolean {
  const protectedRoute = resolveProtectedRoute(pathname);
  if (!protectedRoute) {
    return false;
  }

  return !hasAnyRequiredRole(roles, protectedRoute.requiredRoles);
}

/**
 * Determine whether a login/register path should redirect authenticated users.
 *
 * @param pathname - Current request pathname.
 */
function isAuthEntryPath(pathname: string): boolean {
  return pathname === "/login" || pathname === "/register";
}

/**
 * Determine whether the middleware should simply allow the request through.
 *
 * @param pathname - Current request pathname.
 * @param hint - Verified session hint when present.
 */
function resolveNextDecision(
  pathname: string,
  hint: SessionHint | null,
): AuthRouteDecision {
  if (pathname === "/2fa-challenge" || pathname === "/settings/onboarding") {
    return { kind: "next" };
  }

  if (hint && isAuthEntryPath(pathname)) {
    return landingRedirect(hint.roles);
  }

  if (!hint && isProtectedPath(pathname)) {
    return loginRedirect(pathname);
  }

  if (hint && requiresWrongRoleRedirect(pathname, hint.roles)) {
    return landingRedirect(hint.roles);
  }

  if (!hint && isPublicAuthPath(pathname)) {
    return { kind: "next" };
  }

  return { kind: "next" };
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
  return resolveNextDecision(pathname, hint);
}
