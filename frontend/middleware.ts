/**
 * Next.js auth middleware for browser routing.
 *
 * Reads the signed, non-HttpOnly `session_hint` cookie created by the backend.
 * This cookie is used only for routing decisions; protected API calls still
 * require a verified access token and backend RBAC checks.
 */
import { NextResponse, type NextRequest } from "next/server";

import { resolveAuthRouteDecision } from "./src/lib/auth/route-guards";
import { verifySessionHintCookie } from "./src/lib/auth/session-hint-cookie";

const SESSION_HINT_COOKIE = "session_hint";

/**
 * Resolve the private HMAC secret used to verify session hints.
 *
 * @returns Secret shared with the backend, or null when not configured.
 */
function getSessionHintSecret(): string | null {
  return (
    process.env.SESSION_HINT_SECRET ??
    process.env.SECRET_KEY ??
    process.env.AUTH_SECRET ??
    null
  );
}

/**
 * Gate auth routes and redirect authenticated users away from public login.
 *
 * @param request - Incoming Next.js middleware request.
 */
export async function middleware(request: NextRequest) {
  const secret = getSessionHintSecret();
  const hint = secret
    ? await verifySessionHintCookie(
        request.cookies.get(SESSION_HINT_COOKIE)?.value,
        secret,
      )
    : null;
  const decision = resolveAuthRouteDecision({
    hint,
    pathname: request.nextUrl.pathname,
  });

  if (decision.kind === "redirect") {
    return NextResponse.redirect(new URL(decision.location, request.url));
  }

  return NextResponse.next();
}

export const config = {
  matcher: [
    "/2fa-challenge",
    "/2fa-setup",
    "/admin/:path*",
    "/assignments/:path*",
    "/dashboard/:path*",
    "/forgot-password",
    "/login",
    "/register",
    "/reset-password",
    "/settings/:path*",
    "/verify-email",
  ],
};
