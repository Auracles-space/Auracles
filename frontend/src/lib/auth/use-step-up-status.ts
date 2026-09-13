"use client";

/**
 * Hook exposing the caller's step-up 2FA window.
 *
 * Reads `GET /v1/auth/step-up` once on mount (when a bearer is in memory),
 * then follows the shared step-up store so a prompt answered anywhere on the
 * page updates every subscriber. Ticks so the minutes-left figure and the
 * `active` flag expire without a refetch.
 *
 * Maps to: docs/superpowers/specs/2026-09-13-step-up-and-admin-console-design.md §3.
 */
import { useEffect, useState, useSyncExternalStore } from "react";

import { configureBrowserClient, getAccessTokenHeaders } from "@/lib/auth/form-client";
import { setStepUpVerifiedUntil, stepUpStore } from "@/lib/auth/step-up-gate";
import { authTokenStore } from "@/lib/auth/token-store";
import { readStepUpV1AuthStepUpGet } from "@/lib/generated/sdk.gen";

/** How often the minutes-left figure re-evaluates. */
const TICK_MS = 15_000;

export type StepUpStatus = {
  /** A window is open right now. */
  active: boolean;
  /** Whole minutes left, rounded up; 0 when inactive. */
  minutesLeft: number;
};

function subscribe(listener: () => void): () => void {
  return stepUpStore.subscribe(listener);
}

function readVerifiedUntil(): number | null {
  return stepUpStore.getState().verifiedUntil;
}

/**
 * Report whether the current user holds an open step-up window.
 */
export function useStepUpStatus(): StepUpStatus {
  const verifiedUntil = useSyncExternalStore(
    subscribe,
    readVerifiedUntil,
    () => null,
  );
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!authTokenStore.getState().accessToken) {
      return;
    }
    let cancelled = false;
    async function load() {
      configureBrowserClient();
      let result;
      try {
        result = await readStepUpV1AuthStepUpGet({ headers: getAccessTokenHeaders() });
      } catch {
        return;
      }
      if (cancelled || !result.response.ok || !result.data) {
        return;
      }
      setStepUpVerifiedUntil(
        result.data.active && result.data.verified_until
          ? Date.parse(result.data.verified_until)
          : null,
      );
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (verifiedUntil === null) {
      return;
    }
    setNow(Date.now());
    const timer = window.setInterval(() => setNow(Date.now()), TICK_MS);
    return () => window.clearInterval(timer);
  }, [verifiedUntil]);

  const remainingMs = verifiedUntil === null ? 0 : verifiedUntil - now;
  const active = remainingMs > 0;
  return {
    active,
    minutesLeft: active ? Math.ceil(remainingMs / 60_000) : 0,
  };
}
