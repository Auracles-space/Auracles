/**
 * Date helpers for the attestor organization surfaces.
 *
 * The offers tab, the review queue, and the review workspace all had to answer
 * the same question — how long is left — and each answered it differently (a
 * raw `toLocaleString()`, nothing at all). These pure helpers give every
 * attestor surface one clock and one vocabulary, and are unit tested against a
 * fixed `now` so the wording never depends on when the suite runs.
 *
 * Maps to: docs/superpowers/specs/2026-09-14-attestation-request-to-report-design.md §2
 * (Attestor org).
 */

/** Milliseconds in one hour. */
import { formatShortDate } from "@/lib/marketplace/format";

const HOUR_MS = 3_600_000;

/** Below this many hours the countdown is shown in hours only. */
const HOURS_ONLY_THRESHOLD = 48;

export type OfferExpiry = {
  /** Sentence-cased countdown label, ready to render. */
  label: string;
  /** True once the offer can no longer be accepted. */
  expired: boolean;
};

/**
 * Describe how long an offer has left before it lapses.
 *
 * Under two days the countdown is hours only, because that is the window in
 * which an org has to act; beyond that days lead. An offer whose deadline has
 * passed reads simply "Expired" so the card can be toned as an error.
 *
 * @param expiresAt - ISO timestamp the offer lapses at.
 * @param now - Reference time; defaults to the current time (injected in tests).
 * @returns The countdown label plus whether the offer has already lapsed.
 */
export function describeOfferExpiry(
  expiresAt: string,
  now: Date = new Date(),
): OfferExpiry {
  const expiry = new Date(expiresAt).getTime();
  if (Number.isNaN(expiry)) {
    // A malformed timestamp must not blank the whole offer card.
    return { label: "No expiry date", expired: false };
  }

  const remainingMs = expiry - now.getTime();
  if (remainingMs <= 0) {
    return { label: "Expired", expired: true };
  }

  const hours = Math.floor(remainingMs / HOUR_MS);
  if (hours < 1) {
    return { label: "Expires in under 1 h", expired: false };
  }
  if (hours < HOURS_ONLY_THRESHOLD) {
    return { label: `Expires in ${hours} h`, expired: false };
  }
  return {
    label: `Expires in ${Math.floor(hours / 24)} d ${hours % 24} h`,
    expired: false,
  };
}

/**
 * Format an ISO timestamp as a short, unambiguous date.
 *
 * @param value - ISO timestamp, or null when the API has no date yet.
 * @returns A `17 Sep 2026` style date, or an em dash when there is none.
 */
export function formatAttestationDate(
  value: string | null | undefined,
): string {
  return formatShortDate(value, "\u2014");
}

/**
 * Whether a deadline has already passed.
 *
 * @param dueAt - ISO deadline, or null when none is set.
 * @param now - Reference time; defaults to the current time (injected in tests).
 * @returns True only when a parseable deadline is in the past.
 */
export function isOverdue(
  dueAt: string | null | undefined,
  now: Date = new Date(),
): boolean {
  if (!dueAt) {
    return false;
  }
  const due = new Date(dueAt).getTime();
  return !Number.isNaN(due) && due < now.getTime();
}
