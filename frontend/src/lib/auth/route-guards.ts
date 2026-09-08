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
  // Requestor workspace: contributors/operators request verification on their
  // own frameworks, profiles, or credentials. Attestors receive work through
  // the org offers queue, not here.
  { prefix: "/attestations", requiredRoles: ["contributor", "operator"] },
  { prefix: "/attestor", requiredRoles: ["attestor"] },
  { prefix: "/checkout", requiredRoles: ["operator"] },
  { prefix: "/dashboard/developer", requiredRoles: null },
  // Organizations are cross-role (operators, attestors, and admins own or
  // belong to orgs), so gate on auth presence only. Must precede the
  // contributor-scoped `/dashboard` prefix — first match wins.
  { prefix: "/dashboard/organizations", requiredRoles: null },
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
  // Operator takes precedence: anyone who can license lands on Explore (the
  // marketplace), with the creator dashboard reachable from the authed nav. A
  // pure contributor still lands on their dashboard.
  if (roles.includes("operator")) {
    return "/explore";
  }
  if (roles.includes("contributor")) {
    return "/dashboard";
  }
  if (roles.includes("developer")) {
    return "/dashboard/developer";
  }
  // No active role (e.g. a pending attestor awaiting approval). Land on a route
  // with no role requirement — the contributor `/dashboard` would bounce them
  // straight back here and loop. The attestor application prompt surfaces in
  // the authenticated shell from here.
  return "/settings/identity";
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

/** Roles a user can grant themselves from `/settings/roles`. */
const selfAssignableRoles = new Set(["contributor", "operator"]);

/**
 * Decide where a user who lacks a route's role should be sent.
 *
 * When the missing role is one they could simply add, send them to the page
 * that adds it, carrying the destination so they resume where they meant to
 * be. Landing them somewhere else instead told them nothing about why the page
 * would not open, and — before `/settings/roles` existed — left no way to act.
 *
 * Roles that are granted rather than chosen (admin, attestor) keep the plain
 * landing redirect: offering a control that cannot help would be a worse lie
 * than saying nothing.
 *
 * @param pathname - The route the user tried to open.
 * @param roles - Active session roles from the verified hint.
 * @param requiredRoles - Role requirement of the matched protected prefix.
 */
function wrongRoleRedirect(
  pathname: string,
  roles: string[],
  requiredRoles: string[] | null,
): AuthRouteDecision {
  const addableRoles = (requiredRoles ?? []).filter(
    (role) => selfAssignableRoles.has(role) && !roles.includes(role),
  );
  if (addableRoles.length === 0) {
    return landingRedirect(roles);
  }
  return {
    kind: "redirect",
    location: `/settings/roles?next=${encodeURIComponent(pathname)}`,
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
    return wrongRoleRedirect(
      pathname,
      hint.roles,
      resolveProtectedRoute(pathname)?.requiredRoles ?? null,
    );
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
