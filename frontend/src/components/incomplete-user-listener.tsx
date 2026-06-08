"use client";

/**
 * Global listener that routes incomplete-user 403s to onboarding.
 *
 * Mounted once in the root layout. Subscribes to the
 * `auracles:incomplete-user` window event published by the API response
 * interceptor and pushes the browser to `/settings/onboarding`, preserving
 * the user's original intent via `?next=<encoded-path>&error_code=<code>`.
 *
 * The listener installs the interceptor on mount so generated-client calls
 * issued from any page benefit without per-form wiring.
 *
 * Maps to: Phase 2 cross-cutting concern §6 (Incomplete-user rule).
 */
import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { installIncompleteUserInterceptor } from "@/lib/auth/incomplete-user-interceptor";
import {
  INCOMPLETE_USER_EVENT,
  type IncompleteUserEventDetail,
} from "@/lib/auth/incomplete-user-events";
import { ONBOARDING_PATH } from "@/lib/auth/onboarding";

/**
 * Subscribe to incomplete-user events and redirect when one fires.
 *
 * Renders nothing — this component exists for its effect only.
 */
export function IncompleteUserListener() {
  const router = useRouter();

  useEffect(() => {
    installIncompleteUserInterceptor();

    const handler = (event: Event) => {
      const detail = (event as CustomEvent<IncompleteUserEventDetail>).detail;
      if (!detail) {
        return;
      }
      // Avoid redirect loops if the user is already on the onboarding surface.
      if (window.location.pathname.startsWith(ONBOARDING_PATH)) {
        return;
      }
      const params = new URLSearchParams({
        next: detail.attemptedPath,
        error_code: detail.errorCode,
      });
      router.push(`${ONBOARDING_PATH}?${params.toString()}`);
    };

    window.addEventListener(INCOMPLETE_USER_EVENT, handler);
    return () => window.removeEventListener(INCOMPLETE_USER_EVENT, handler);
  }, [router]);

  return null;
}
