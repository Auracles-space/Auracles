import type { ReactNode } from "react";
import type { AttestationRequestResponse } from "@/lib/generated/types.gen";
import { formatLabel, formatMoney } from "@/lib/marketplace/format";

/**
 * Requestor-facing labels for internal attestation statuses.
 *
 * The stored status names are operational (e.g. ``needs_admin`` means auto-match
 * found no attestor and a human must assign one). These map them to plain,
 * requestor-friendly wording; unmapped statuses fall back to title-casing.
 */
const STATUS_LABELS: Record<string, string> = {
  pending_fee: "Awaiting payment",
  matching: "Finding attestor",
  needs_admin: "Finding attestor",
  offered: "Offer sent",
  report_submitted: "Report ready",
};

/**
 * Render a compact status tag.
 *
 * @param value - Raw status value from the API.
 */
export function StatusTag({ value }: { value: string }) {
  let classes = "border-info/30 bg-info/10 text-info";
  if (["pending", "offered", "in_review", "needs_admin"].includes(value)) {
    classes = "border-warning/30 bg-warning/10 text-warning";
  } else if (
    ["approved", "completed", "accepted", "verified", "active", "report_submitted"].includes(value)
  ) {
    classes = "border-success/30 bg-success/10 text-success";
  } else if (["rejected", "declined", "withdrawn", "failed"].includes(value)) {
    classes = "border-error/30 bg-error/10 text-error";
  }
  return (
    <span
      className={`inline-flex rounded-badge border px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.05em] ${classes}`}
    >
      {STATUS_LABELS[value] ?? formatLabel(value)}
    </span>
  );
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

/**
 * Render one Attestation card.
 */
export function AttestationCard({
  attestation,
  children,
}: {
  attestation: AttestationRequestResponse;
  children?: ReactNode;
}) {
  return (
    <article className="rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="font-heading text-lg font-bold text-foreground">
            {formatLabel(attestation.target_type)} · {attestation.target_id}
          </h2>
          <p className="mt-1 text-sm text-foreground-muted">
            Fee {formatMoney(attestation.fee_amount, attestation.currency)} ·{" "}
            {attestation.outcome ? formatLabel(attestation.outcome) : "No outcome"}
          </p>
        </div>
        <StatusTag value={attestation.status} />
      </div>
      {attestation.summary ? (
        <p className="mt-4 text-sm leading-6 text-foreground-muted">
          {attestation.summary}
        </p>
      ) : null}
      {children}
    </article>
  );
}
