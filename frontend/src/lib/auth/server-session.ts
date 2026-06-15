/**
 * Server-side session-hint helpers for authenticated layouts.
 *
 * Reads the signed `session_hint` cookie inside React Server Components so the
 * authenticated shell can render the correct role-filtered navigation without
 * a client-side flash of privileged links.
 */
import { cookies } from "next/headers";

import type { SessionHint } from "./session-hint-cookie";
import { verifySessionHintCookie } from "./session-hint-cookie";

/**
 * Verify the current request's session hint from server cookies.
 *
 * Missing secrets or invalid signatures fail closed as `null`.
 */
export async function getVerifiedSessionHintFromCookies(): Promise<SessionHint | null> {
  const secret = process.env.SESSION_HINT_SECRET;
  if (!secret) {
    return null;
  }

  const cookieStore = await cookies();
  const cookieValue = cookieStore.get("session_hint")?.value;
  try {
    return await verifySessionHintCookie(cookieValue, secret);
  } catch {
    return null;
  }
}
