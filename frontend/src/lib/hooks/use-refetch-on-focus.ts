import { useEffect } from "react";

/**
 * Re-run a fetch when the user returns to the tab.
 *
 * Fires the callback on window focus and on the tab becoming visible again,
 * so badge counts refresh without background polling — zero traffic while the
 * user is away, one refetch when they come back.
 *
 * @param refetch - Stable callback (wrap in useCallback) that reloads data.
 *   It should refetch silently, without toggling a full-page loading state.
 */
export function useRefetchOnFocus(refetch: () => void): void {
  useEffect(() => {
    function onFocus(): void {
      refetch();
    }
    function onVisibilityChange(): void {
      if (document.visibilityState === "visible") {
        refetch();
      }
    }
    window.addEventListener("focus", onFocus);
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => {
      window.removeEventListener("focus", onFocus);
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, [refetch]);
}
