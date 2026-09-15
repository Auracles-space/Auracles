/**
 * Cross-component org UI events.
 *
 * The org shell renders tab pages as route children, so a child (e.g. the NDA
 * panel) cannot call back into the shell directly. These lightweight window
 * events bridge that gap so the shell can refresh its badges/dots immediately.
 */

/** Fired after the current member signs the org NDA. */
export const NDA_SIGNED_EVENT = "auracles:nda-signed";

/** Emit the NDA-signed event so the shell clears its NDA dot. */
export function emitNdaSigned(): void {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event(NDA_SIGNED_EVENT));
  }
}

/** Fired after the org's attestor application is created or changed. */
export const ATTESTOR_APPLICATION_CHANGED_EVENT = "auracles:attestor-application-changed";

/**
 * Emit the attestor-application-changed event so the shell re-reads NDA
 * status: a live application makes the NDA required.
 */
export function emitAttestorApplicationChanged(): void {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event(ATTESTOR_APPLICATION_CHANGED_EVENT));
  }
}
