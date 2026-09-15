"use client";

/**
 * One review card in the attestor organization's queue.
 *
 * Used for both the active queue and the history list, which differ only in
 * the actions they offer and whether a passed deadline still counts as
 * overdue. Card layout, not a table row: it stacks on a phone.
 *
 * Maps to: docs/superpowers/specs/2026-09-14-attestation-request-to-report-design.md §2
 * (Attestor org).
 */
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { StatusPill, attestationStatusKey } from "@/components/ui/status-pill";
import type { OrgAttestationItem } from "@/lib/generated/types.gen";
import { formatLabel } from "@/lib/marketplace/format";

import { formatAttestationDate, isOverdue } from "./attestation-dates";

/**
 * Deadline line for one queue card.
 *
 * A deadline only counts as missed while the review is still owed work, so a
 * finished review never carries a red "Overdue".
 *
 * @param dueAt - ISO completion deadline, or null when none is set.
 * @param active - Whether the review is still in flight.
 */
function DueLine({ dueAt, active }: { dueAt: string | null; active: boolean }) {
  if (!dueAt) {
    return null;
  }
  const overdue = active && isOverdue(dueAt);
  return (
    <p className={`text-sm ${overdue ? "text-error" : "text-foreground-muted"}`}>
      <span>Due {formatAttestationDate(dueAt)}</span>
      {overdue ? <span className="text-error"> · Overdue</span> : null}
    </p>
  );
}

type QueueCardProps = {
  /** The attestation this card represents. */
  attestation: OrgAttestationItem;
  /** Whether the review is still in the active queue. */
  active: boolean;
  /** Whether the viewer can reassign the reviewing member. */
  isAdmin: boolean;
  /** Open the review workspace. */
  onOpen: () => void;
  /** Start reassigning the reviewing member (before the review starts). */
  onReassign: () => void;
};

/**
 * Render one queue card with its status, deadline, and actions.
 *
 * @param props - The attestation, its queue side, viewer rights, callbacks.
 */
export function QueueCard({
  attestation,
  active,
  isAdmin,
  onOpen,
  onReassign,
}: QueueCardProps) {
  return (
    <article className="flex flex-col justify-between gap-4 rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm md:flex-row md:items-center">
      <div className="space-y-1">
        <div className="flex flex-wrap items-center gap-2">
          {attestation.unread_answer ? (
            <span
              aria-label="Clarification answer awaiting your review"
              className="h-2.5 w-2.5 flex-shrink-0 rounded-full bg-error"
              role="img"
            />
          ) : null}
          <h3 className="font-heading text-base font-bold text-foreground">
            {attestation.target_title ?? formatLabel(attestation.target_type)}
          </h3>
          <StatusPill
            status={attestationStatusKey(attestation.status, "attestor")}
          />
          {attestation.unread_answer ? (
            <Badge variant="error">Answer received</Badge>
          ) : null}
          {!active && attestation.outcome ? (
            <Badge variant="default">{formatLabel(attestation.outcome)}</Badge>
          ) : null}
        </div>
        <p className="text-sm text-foreground-muted">
          {attestation.review_type
            ? `${formatLabel(attestation.review_type)} review`
            : "Attestation"}
          {active
            ? ` · ${formatLabel(attestation.target_type)}`
            : attestation.updated_at
              ? ` · ${formatAttestationDate(attestation.updated_at)}`
              : ""}
        </p>
        <DueLine active={active} dueAt={attestation.completion_due_at} />
        {isAdmin ? (
          <p className="text-sm text-foreground-muted">
            {active ? "Assigned to" : "Reviewed by"}:{" "}
            {attestation.reviewing_member_name ?? (active ? "Unassigned" : "—")}
          </p>
        ) : null}
      </div>

      <div className="flex flex-col gap-2 sm:flex-row">
        {/* The server allows reassignment only before the reviewer starts
            (status still "accepted"); after that it needs an admin. */}
        {active && attestation.status === "accepted" ? (
          <Button disabled={!isAdmin} onClick={onReassign} variant="secondary">
            Reassign
          </Button>
        ) : null}
        <Button onClick={onOpen} variant="secondary">
          {active ? "Workspace" : "View"}
        </Button>
      </div>
    </article>
  );
}
