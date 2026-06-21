"use client";

/**
 * Global listener that signs the user out on a terminal account state.
 *
 * Mounted once in the root layout. Subscribes to the
 * `auracles:session-terminated` window event published by the API response
 * interceptor (fired on a 403 with `account_deactivated` / `account_suspended`).
 * On fire it clears the in-memory access token, best-effort revokes the
 * server-side refresh/session cookies, and redirects to `/login` with a reason
 * so the user understands why they were signed out.
 */
import { useRouter } from "next/navigation";
import { useEffect } from "react";

import {
  configureBrowserClient,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import { installSessionTerminatedInterceptor } from "@/lib/auth/session-terminated-interceptor";
import {
  SESSION_TERMINATED_EVENT,
  type SessionTerminatedEventDetail,
} from "@/lib/auth/session-terminated-events";
import { clearAuthToken } from "@/lib/auth/token-store";
import { logoutV1AuthLogoutPost } from "@/lib/generated/sdk.gen";

/**
 * Subscribe to terminal-session events and force a logout when one fires.
 *
 * Renders nothing — this component exists for its effect only.
 */
export function SessionTerminatedListener() {
  const router = useRouter();

  useEffect(() => {
    installSessionTerminatedInterceptor();

    let handled = false;
    const handler = (event: Event) => {
      const detail = (event as CustomEvent<SessionTerminatedEventDetail>).detail;
      if (!detail || handled) {
        return;
      }
      handled = true;

      // Clear the in-memory bearer immediately so no further request goes out
      // with a token the backend has already rejected.
      configureBrowserClient();
      void logoutV1AuthLogoutPost({ headers: getAccessTokenHeaders() }).catch(
        () => {
          // Best-effort: the account may already be gone; cookie cleanup on the
          // server is not required for the client to stop using the session.
        },
      );
      clearAuthToken();

      if (window.location.pathname === "/login") {
        return;
      }
      router.replace(`/login?reason=${encodeURIComponent(detail.errorCode)}`);
    };

    window.addEventListener(SESSION_TERMINATED_EVENT, handler);
    return () => window.removeEventListener(SESSION_TERMINATED_EVENT, handler);
  }, [router]);

  return null;
}
