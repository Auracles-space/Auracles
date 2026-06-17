"use client";

/**
 * Authenticated-session bootstrap gate.
 *
 * Access tokens are memory-only, so a hard reload (e.g. landing on a protected
 * page straight after login) leaves a valid `session_hint` and refresh cookie
 * but no bearer token in the client store. Without this gate, the first child
 * component that fetches on mount sends a request with no `Authorization`
 * header and the backend rejects it with "Missing access token".
 *
 * Rendered once inside the authenticated shell, this gate rehydrates the token
 * from the refresh session before any child mounts. Children only render once a
 * token is present; a truly dead session is cleared and bounced to login.
 */
import { useEffect, useState } from "react";
import type { ReactNode } from "react";

import {
  clearBrowserSessionHintCookie,
  ensureBrowserAccessToken,
} from "@/lib/auth/current-user-session";
import { authTokenStore, clearAuthToken } from "@/lib/auth/token-store";

type BrowserSessionGateProps = {
  children: ReactNode;
};

type GateStatus = "pending" | "ready" | "expired";

/**
 * Block authenticated children until the in-memory access token is restored.
 *
 * @param props - The protected content to render once a token is present.
 */
export function BrowserSessionGate({ children }: BrowserSessionGateProps) {
  // A client-side navigation between authed pages keeps the token in memory, so
  // start "ready" and skip the refresh round-trip (and its loading flash).
  const [status, setStatus] = useState<GateStatus>(() =>
    authTokenStore.getState().accessToken ? "ready" : "pending",
  );

  useEffect(() => {
    if (status !== "pending") {
      return;
    }

    let active = true;
    void (async () => {
      const hasToken = await ensureBrowserAccessToken();
      if (!active) {
        return;
      }
      if (hasToken) {
        setStatus("ready");
        return;
      }
      // Refresh failed: the session is dead. Clear local remnants so stale
      // hints cannot keep bouncing the user, then send them to log in again.
      clearAuthToken();
      clearBrowserSessionHintCookie();
      setStatus("expired");
      location.assign("/login");
    })();

    return () => {
      active = false;
    };
  }, [status]);

  if (status === "ready") {
    return <>{children}</>;
  }

  return (
    <div
      className="flex min-h-[40vh] w-full items-center justify-center"
      role="status"
      aria-live="polite"
    >
      <div className="flex items-center gap-3 text-sm text-foreground-muted">
        <span
          aria-hidden
          className="h-4 w-4 animate-spin rounded-full border-2 border-border-default border-t-accent"
        />
        Restoring your session…
      </div>
    </div>
  );
}
