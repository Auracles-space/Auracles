/**
 * Frontend auth-gating middleware.
 *
 * Verifies the signed `session_hint` cookie and applies pure route decisions
 * before any protected route renders. Backend RBAC remains authoritative; this
 * middleware exists for UX and route-level information disclosure only.
 */
import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

import { resolveAuthRouteDecision } from "@/lib/auth/route-guards";
import { verifySessionHintCookie } from "@/lib/auth/session-hint-cookie";

/**
 * Apply route-lock decisions from the verified session-hint cookie.
 *
 * Missing or invalid secrets fail closed by treating the hint as absent.
 *
 * @param request - Incoming Next.js middleware request.
 */
export async function middleware(request: NextRequest) {
  const secret = process.env.SESSION_HINT_SECRET;
  const cookieValue = request.cookies.get("session_hint")?.value;
  const hint = secret
    ? await verifySessionHintCookie(cookieValue, secret).catch(() => null)
    : null;
  const decision = resolveAuthRouteDecision({
    hint,
    pathname: request.nextUrl.pathname,
  });

  if (decision.kind === "next") {
    const requestHeaders = new Headers(request.headers);
    requestHeaders.set("x-auracles-pathname", request.nextUrl.pathname);
    return NextResponse.next({
      request: {
        headers: requestHeaders,
      },
    });
  }

  const redirectUrl = request.nextUrl.clone();
  const parsedLocation = new URL(decision.location, request.url);
  redirectUrl.pathname = parsedLocation.pathname;
  redirectUrl.search = parsedLocation.search;
  return NextResponse.redirect(redirectUrl);
}

// Next.js statically analyzes this export at build time: `matcher` must be an
// inline string-array literal, not a referenced constant, or the build fails
// with "Invalid segment configuration export".
export const config = {
  matcher: [
    "/2fa-challenge",
    "/2fa-setup/:path*",
    "/admin/:path*",
    "/attestations/:path*",
    "/attestor/:path*",
    "/checkout/:path*",
    "/dashboard/:path*",
    "/library/:path*",
    "/login",
    "/projects/:path*",
    "/register",
    "/settings/:path*",
  ],
};
