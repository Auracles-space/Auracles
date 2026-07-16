/**
 * Cross-component admin workspace events.
 *
 * Decouples the admin attestation panel (which resolves needs-admin requests)
 * from the workspace shell (which shows the needs-admin count badge): the panel
 * fires this event on resolve, and the shell refetches the count.
 */

/** Fired when a needs-admin attestation is assigned or refunded. */
export const NEEDS_ADMIN_CHANGED_EVENT = "auracles:needs-admin-changed";

/** Dispatch the needs-admin-changed event (no-op during SSR). */
export function emitNeedsAdminChanged(): void {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event(NEEDS_ADMIN_CHANGED_EVENT));
  }
}
