"use client";

/**
 * Load-once data hook for the admin organization detail tabs.
 *
 * Each tab owns one read endpoint; this hook runs it when the tab first
 * mounts (and again when the loader identity changes, e.g. a new audit page),
 * exposes a described error, and a `retry` that refetches without a reload.
 *
 * Maps to: organizations end-to-end design, Slice D (admin org detail).
 */
import { useCallback, useEffect, useState } from "react";

import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";

/** The generated client's result envelope, reduced to what the hook reads. */
export type SdkResult<T> = { data?: T; error?: unknown; response: Response };

/** Loader receiving the bearer headers for the generated client. */
export type OrgResourceLoader<T> = (headers: Record<string, string>) => Promise<SdkResult<T>>;

type ResourceState<T> = { data: T | null; error: string | null; loading: boolean };

/**
 * Fetch one admin organization resource with loading, error and retry state.
 *
 * @param load - Memoised loader; a new identity triggers a refetch.
 * @returns The data, a described error, loading flag, retry and a local setter.
 */
export function useAdminOrgResource<T>(load: OrgResourceLoader<T>) {
  const [state, setState] = useState<ResourceState<T>>({ data: null, error: null, loading: true });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    async function run(): Promise<void> {
      setState((previous) => ({ ...previous, error: null, loading: true }));
      configureBrowserClient();
      try {
        const result = await load(getAccessTokenHeaders());
        if (cancelled) return;
        if (!result.response.ok || !result.data) {
          setState({ data: null, error: describeGeneratedError(result.error), loading: false });
          return;
        }
        setState({ data: result.data, error: null, loading: false });
      } catch {
        if (!cancelled) {
          setState({ data: null, error: "Could not reach the server. Try again.", loading: false });
        }
      }
    }
    void run();
    return () => {
      cancelled = true;
    };
  }, [load, attempt]);

  const retry = useCallback(() => setAttempt((value) => value + 1), []);
  const setData = useCallback((data: T) => setState((previous) => ({ ...previous, data })), []);

  return { ...state, retry, setData };
}
