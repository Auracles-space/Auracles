/**
 * Cross-panel attestation workspace events.
 *
 * The rubric and report panels are siblings in the reviewer's workspace. The
 * report's word counter includes rubric comment words, so it must hear when a
 * rubric row is saved rather than reading the count once on mount.
 */

/** Fired after a rubric score or comment is saved. */
export const RUBRIC_SAVED_EVENT = "auracles:rubric-saved";

/** Emit the rubric-saved event so the report panel recounts comment words. */
export function emitRubricSaved(): void {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event(RUBRIC_SAVED_EVENT));
  }
}
