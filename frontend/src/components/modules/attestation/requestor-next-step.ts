/**
 * Requestor-facing "what happens next" sentence for one Attestation.
 *
 * The stored status is operational and, on its own, tells a requestor nothing
 * about whether they must act, wait, or are finished. This turns each status
 * into one plain sentence, the date that matters for it, and a semantic tone,
 * so the list card and the detail page say exactly the same thing.
 *
 * Maps to: docs/superpowers/specs/2026-09-14-attestation-request-to-report-design.md §2.
 */
import { formatShortDate } from "@/lib/marketplace/format";
import type { StatusTone } from "@/components/ui/status-pill";
import type { AttestationRequestResponse } from "@/lib/generated/types.gen";

export type RequestorNextStep = {
  /** One plain sentence telling the requestor what happens next. */
  text: string;
  /** Raw ISO timestamp the sentence refers to, when there is one. */
  date?: string | null;
  /** Semantic tone for the surrounding card. */
  tone: StatusTone;
};

// Written out rather than delegated to Intl: the ICU short-month string drifts
// between runtimes ("Sep" vs "Sept" for September), and a deadline that reads
// differently on two devices is a support ticket.
/**
 * Format an ISO timestamp as a short, unambiguous date.
 *
 * Day-first with a named month so "09/10" is never read as the wrong month.
 * Rendered in UTC, matching the deadlines the backend stores.
 *
 * @param value - ISO timestamp, or null/undefined when absent.
 * @returns The formatted date, or an empty string when there is none.
 */
export function formatAttestationDate(
  value: string | null | undefined,
): string {
  return formatShortDate(value);
}

/**
 * Describe the requestor's next step for one Attestation.
 *
 * @param attestation - The attestation as returned to its requestor.
 * @returns The sentence, the date it refers to, and a tone.
 */
export function requestorNextStep(
  attestation: AttestationRequestResponse,
): RequestorNextStep {
  const org = attestation.attestor_org_name || "The attestor";
  const completionDue = formatAttestationDate(attestation.completion_due_at);
  const disputeDue = formatAttestationDate(attestation.dispute_window_ends_at);
  const decisionDue = formatAttestationDate(
    attestation.dispute?.resolution_due_at,
  );

  switch (attestation.status) {
    case "pending_owner_consent":
      return {
        text: "Waiting for the framework owner to approve your request.",
        date: attestation.created_at,
        tone: "warning",
      };
    case "pending_fee":
      return {
        text: "Pay the fee to start matching.",
        date: attestation.created_at,
        tone: "warning",
      };
    // The admin assignment step is invisible to the requestor: to them a
    // request that auto-matching could not place is still being matched.
    case "matching":
    case "needs_admin":
      return {
        text: "We are finding an attestor organization. You can still withdraw.",
        date: attestation.created_at,
        tone: "info",
      };
    case "offered":
      return {
        text: "An attestor organization is considering your request. You can still withdraw.",
        date: attestation.created_at,
        tone: "info",
      };
    case "accepted":
    case "in_review":
      return {
        text: completionDue
          ? `${org} is reviewing. Report due ${completionDue}.`
          : `${org} is reviewing.`,
        date: attestation.completion_due_at ?? attestation.accepted_at,
        tone: "info",
      };
    case "report_submitted":
      return {
        text: disputeDue
          ? `Read the report, then accept it or dispute it by ${disputeDue}.`
          : "Read the report, then accept it or dispute it.",
        date: attestation.dispute_window_ends_at,
        tone: "success",
      };
    case "revision_requested":
      return {
        text: completionDue
          ? `The attestor is revising the report. Due ${completionDue}.`
          : "The attestor is revising the report.",
        date: attestation.completion_due_at,
        tone: "warning",
      };
    case "disputed":
      return {
        text: decisionDue
          ? `Your dispute is with the trust team. Decision due ${decisionDue}.`
          : "Your dispute is with the trust team.",
        date: attestation.dispute?.resolution_due_at,
        tone: "error",
      };
    // `closed` is the legacy settled value written before release and refund
    // were told apart; it still means the fee went to the attestor.
    case "released":
    case "closed":
      return {
        text: "Complete. Rate the attestor and download your invoice.",
        date: attestation.closed_at,
        tone: "success",
      };
    case "refunded":
      return {
        text: "The fee was refunded.",
        date: attestation.closed_at,
        tone: "neutral",
      };
    case "cancelled":
      return {
        text: "You withdrew this request.",
        date: attestation.closed_at ?? attestation.updated_at,
        tone: "neutral",
      };
    default:
      return {
        text: "This request is in progress.",
        date: attestation.updated_at,
        tone: "neutral",
      };
  }
}
