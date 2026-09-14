import type { AttestationDisputeCreateRequest } from "@/lib/generated/types.gen";

/** Dispute categories the backend accepts on a report dispute. */
export type DisputeCategory = AttestationDisputeCreateRequest["category"];

/**
 * Dispute categories in display order, each with its human label.
 *
 * Both the requestor's dispute form and the read-only dispute cards (requestor,
 * attestor workspace) use this one list so the words match everywhere.
 */
export const DISPUTE_CATEGORIES: readonly (readonly [DisputeCategory, string])[] = [
  ["scope_error", "Scope error"],
  ["process_violation", "Process violation"],
  ["material_inaccuracy", "Material inaccuracy"],
  ["conflict_of_interest", "Conflict of interest"],
];

/**
 * Human label for a dispute category; unknown values are title-cased.
 *
 * @param category - Raw category from the API.
 */
export function describeDisputeCategory(category: string): string {
  const match = DISPUTE_CATEGORIES.find(([value]) => value === category);
  if (match) return match[1];
  return category
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

/**
 * Convert comma-separated user input into API array fields.
 *
 * @param value - Comma-separated text.
 */
export function splitCsv(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

// Mirror the backend input-hardening rules so the form blocks unsafe data
// before it is sent. Labels accept a safe charset only; prose rejects markup
// and control characters. Keep these in sync with attestation/schemas.py.
const LABEL_PATTERN = /^[A-Za-z0-9][A-Za-z0-9 .,&/()-]*$/;
// Markup delimiters plus ASCII control chars (tab/newline/return excepted).
const PROSE_FORBIDDEN = /[<>\u0000-\u0008\u000b\u000c\u000e-\u001f]/;

/**
 * Whether every comma-separated label uses only the safe charset.
 *
 * @param value - Raw comma-separated input.
 */
export function areLabelsSafe(value: string): boolean {
  const items = splitCsv(value);
  return items.length > 0 && items.every((item) => LABEL_PATTERN.test(item));
}

/**
 * Whether free-text prose is free of markup and control characters.
 *
 * @param value - Raw prose input.
 */
export function isProseSafe(value: string): boolean {
  return !PROSE_FORBIDDEN.test(value);
}

/**
 * Show user-facing request errors.
 */
export function ErrorMessage({ message }: { message: string | null }) {
  if (!message) {
    return null;
  }
  return <p className="rounded-xl border border-error/30 bg-error/10 p-4 text-sm text-error">{message}</p>;
}

/**
 * Shared page header card for Attestation surfaces.
 */
export function HeaderCard({
  eyebrow,
  summary,
  title,
}: {
  eyebrow: string;
  summary: string;
  title: string;
}) {
  return (
    <div className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
      <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
        {eyebrow}
      </p>
      <h1 className="mt-2 font-heading text-3xl font-bold text-foreground">
        {title}
      </h1>
      <p className="mt-2 max-w-3xl text-sm leading-6 text-foreground-muted">
        {summary}
      </p>
    </div>
  );
}
