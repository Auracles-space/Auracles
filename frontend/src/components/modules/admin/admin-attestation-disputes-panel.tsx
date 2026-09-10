"use client";

/**
 * Admin Attestation-dispute queue and resolution controls.
 *
 * Attestation disputes had no queue: the only admin surface was a free-text
 * dispute-ID box, and no screen anywhere handed an admin that id, so an open
 * dispute was unreachable in practice. This panel enumerates them and resolves
 * one in place.
 *
 * Maps to: FR-ATT-* (dispute resolution).
 */

import { useCallback, useEffect, useState } from "react";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import {
  listAdminAttestationDisputes,
  resolveAttestationDispute,
} from "@/lib/generated/sdk.gen";
import type { AdminAttestationDisputeListItem } from "@/lib/generated/types.gen";
import { formatLabel, formatMoney } from "@/lib/marketplace/format";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";
import { TableSkeleton } from "@/components/ui/skeletons/table-skeleton";

type StatusFilter = "active" | "open" | "under_review" | "resolved";

type Outcome = "rejected" | "upheld_refund" | "upheld_revise";

/**
 * The three verdicts the API implements, each stating where the money goes.
 *
 * The consequence text is not decoration: every option moves escrow, and an
 * admin picking blind is how escrow gets released by accident.
 */
const OUTCOMES: { value: Outcome; label: string; consequence: string }[] = [
  {
    value: "rejected",
    label: "Reject the dispute",
    consequence:
      "The report stands. Escrow releases to the Attestor and the badge publishes.",
  },
  {
    value: "upheld_refund",
    label: "Uphold — refund the requester",
    consequence:
      "The report is withdrawn. Escrow refunds in full and no badge publishes.",
  },
  {
    value: "upheld_revise",
    label: "Uphold — require a revision",
    consequence:
      "Escrow stays held. The Attestor gets a new deadline to revise the report.",
  },
];

const STATUS_FILTERS: { label: string; value: StatusFilter }[] = [
  { label: "Active", value: "active" },
  { label: "Open", value: "open" },
  { label: "In review", value: "under_review" },
  { label: "Resolved", value: "resolved" },
];

/**
 * Render one dispute's due date with its urgency.
 *
 * @param dispute - The dispute whose SLA is being described.
 */
function DueBadge({ dispute }: { dispute: AdminAttestationDisputeListItem }) {
  if (dispute.resolved_at) {
    return (
      <span className="inline-flex rounded-badge border border-success/30 bg-success/10 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.05em] text-success">
        Resolved
      </span>
    );
  }
  if (!dispute.resolution_due_at) return null;
  const due = new Date(dispute.resolution_due_at);
  const overdue = due.getTime() < Date.now();
  const classes = overdue
    ? "border-error/30 bg-error/10 text-error"
    : "border-info/30 bg-info/10 text-info";
  return (
    <span
      className={`inline-flex rounded-badge border px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.05em] ${classes}`}
    >
      {overdue ? "Overdue" : "Due"} {due.toLocaleDateString()}
    </span>
  );
}

/**
 * Render the Attestation dispute queue with inline resolution.
 */
export function AdminAttestationDisputesPanel() {
  const [disputes, setDisputes] = useState<AdminAttestationDisputeListItem[]>([]);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("active");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [openId, setOpenId] = useState<string | null>(null);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const [notes, setNotes] = useState("");
  const [totp, setTotp] = useState("");
  const [isComplex, setIsComplex] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);

  const loadDisputes = useCallback(async (status: StatusFilter) => {
    setLoading(true);
    setError(null);
    configureBrowserClient();
    try {
      const result = await listAdminAttestationDisputes({
        headers: getAccessTokenHeaders(),
        query: { status },
      });
      if (!result.response.ok || !result.data) {
        setError(describeGeneratedError(result.error));
        return;
      }
      setDisputes(result.data.disputes);
    } catch {
      setError("Failed to load the dispute queue.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadDisputes(statusFilter);
  }, [loadDisputes, statusFilter]);

  /** Close the resolution form and drop whatever was typed into it. */
  function resetForm() {
    setOpenId(null);
    setOutcome(null);
    setNotes("");
    setTotp("");
    setIsComplex(false);
  }

  /**
   * Open the resolution form for one dispute on a clean slate.
   *
   * One form's state is shared across rows, so opening a second dispute
   * without clearing would carry the first one's verdict and notes over — and
   * submit them against the wrong dispute's escrow.
   *
   * @param dispute - The dispute whose form is being opened.
   */
  function openForm(dispute: AdminAttestationDisputeListItem) {
    setOpenId(dispute.id);
    setOutcome(null);
    setNotes("");
    setTotp("");
    // An already-complex dispute must not read as standard-SLA in the form.
    setIsComplex(dispute.is_complex);
  }

  /**
   * Submit the chosen verdict for one dispute.
   *
   * @param disputeId - The dispute the open form belongs to.
   */
  async function handleResolve(disputeId: string) {
    if (!outcome) return;
    setError(null);
    setNotice(null);
    setBusyId(disputeId);
    configureBrowserClient();
    try {
      const result = await resolveAttestationDispute({
        headers: getAccessTokenHeaders(),
        path: { dispute_id: disputeId },
        body: {
          outcome,
          resolution_notes: notes,
          totp_code: totp,
          is_complex: isComplex,
        },
      });
      if (!result.response.ok) {
        setError(describeGeneratedError(result.error));
        return;
      }
      setNotice(
        OUTCOMES.find((item) => item.value === outcome)?.consequence ??
          "Dispute resolved.",
      );
      resetForm();
      await loadDisputes(statusFilter);
    } catch {
      setError("Failed to resolve the dispute.");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
      <h3 className="font-heading text-xl font-bold text-foreground">
        Attestation disputes{loading ? "" : ` (${disputes.length})`}
      </h3>
      <p className="mt-1 text-sm text-foreground-muted">
        Requesters who dispute a submitted report land here. Every verdict moves
        escrow, so each option states what it pays out before you confirm.
      </p>

      <nav
        aria-label="Filter disputes by status"
        className="mt-4 flex flex-wrap gap-1 rounded-2xl border border-border-default bg-surface-2 p-1.5"
      >
        {STATUS_FILTERS.map((filter) => {
          const isActive = filter.value === statusFilter;
          return (
            <button
              aria-pressed={isActive}
              className={[
                "min-h-11 flex-1 whitespace-nowrap rounded-xl px-4 text-sm font-semibold outline-none transition-all",
                isActive
                  ? "bg-foreground text-background shadow-sm"
                  : "text-foreground-muted hover:bg-surface-1 hover:text-foreground",
              ].join(" ")}
              key={filter.value}
              onClick={() => setStatusFilter(filter.value)}
              type="button"
            >
              {filter.label}
            </button>
          );
        })}
      </nav>

      {error ? (
        <p className="mt-4 rounded-xl border border-error/30 bg-error/10 p-4 text-sm text-error">
          {error}
        </p>
      ) : null}
      {notice ? (
        <p className="mt-4 rounded-xl border border-success/30 bg-success/10 p-4 text-sm text-success">
          {notice}
        </p>
      ) : null}

      <div className="mt-4 grid gap-3">
        {loading ? (
          <TableSkeleton />
        ) : disputes.length === 0 ? (
          <p className="rounded-xl border border-border-default bg-surface-2 p-4 text-sm text-foreground-muted">
            No disputes in this status.
          </p>
        ) : (
          disputes.map((dispute) => (
            <article
              className="rounded-xl border border-border-default bg-surface-2 p-4"
              key={dispute.id}
            >
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="font-heading text-sm font-bold text-foreground">
                    {dispute.attestor_org_name ?? "Unassigned attestor"}
                  </p>
                  <p className="mt-1 text-xs text-foreground-muted">
                    {dispute.review_type
                      ? `${formatLabel(dispute.review_type)} review`
                      : "Attestation"}
                    {dispute.fee_amount
                      ? ` · ${formatMoney(dispute.fee_amount, dispute.currency ?? undefined)} held`
                      : ""}
                  </p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <span className="inline-flex rounded-badge border border-warning/30 bg-warning/10 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.05em] text-warning">
                    {formatLabel(dispute.category)}
                  </span>
                  <DueBadge dispute={dispute} />
                </div>
              </div>
              <p className="mt-3 text-sm text-foreground">{dispute.reason}</p>

              {dispute.resolved_at ? (
                <p className="mt-3 text-xs text-foreground-muted">
                  Verdict: {formatLabel(dispute.outcome ?? "resolved")}
                </p>
              ) : (
                <Button
                  className="mt-3"
                  onClick={() =>
                    openId === dispute.id ? resetForm() : openForm(dispute)
                  }
                  variant="secondary"
                >
                  {openId === dispute.id ? "Cancel" : "Resolve"}
                </Button>
              )}

              {openId === dispute.id ? (
                <div className="mt-3 grid gap-4 rounded-xl border border-border-default bg-surface-1 p-4">
                  <fieldset className="grid gap-2">
                    <legend className="mb-2 text-xs font-semibold uppercase tracking-[0.05em] text-foreground-muted">
                      Verdict
                    </legend>
                    {OUTCOMES.map((option) => (
                      <label
                        className={[
                          "grid cursor-pointer gap-1 rounded-xl border p-3 transition-colors",
                          outcome === option.value
                            ? "border-accent bg-accent/5"
                            : "border-border-default hover:bg-surface-2",
                        ].join(" ")}
                        key={option.value}
                      >
                        <span className="flex items-center gap-2 text-sm font-semibold text-foreground">
                          <input
                            checked={outcome === option.value}
                            className="h-4 w-4 accent-accent"
                            name={`outcome-${dispute.id}`}
                            onChange={() => setOutcome(option.value)}
                            type="radio"
                            value={option.value}
                          />
                          {option.label}
                        </span>
                        <span className="pl-6 text-xs text-foreground-muted">
                          {option.consequence}
                        </span>
                      </label>
                    ))}
                  </fieldset>

                  <label className="flex items-center gap-2 text-sm text-foreground">
                    <input
                      checked={isComplex}
                      className="h-4 w-4 accent-accent"
                      onChange={(event) => setIsComplex(event.target.checked)}
                      type="checkbox"
                    />
                    Complex dispute (extends the resolution SLA to 15 business
                    days)
                  </label>

                  <label className="grid gap-2 text-xs font-semibold uppercase tracking-[0.05em] text-foreground-muted">
                    Resolution notes
                    <Textarea
                      onChange={(event) => setNotes(event.target.value)}
                      placeholder="Explain this verdict for the audit log"
                      value={notes}
                    />
                  </label>

                  <label className="grid gap-2 text-xs font-semibold uppercase tracking-[0.05em] text-foreground-muted">
                    Admin 2FA code
                    <Input
                      inputMode="numeric"
                      onChange={(event) => setTotp(event.target.value)}
                      placeholder="6-digit code"
                      value={totp}
                    />
                  </label>

                  <Button
                    disabled={
                      busyId === dispute.id ||
                      !outcome ||
                      notes.trim().length < 5 ||
                      totp.trim().length < 6
                    }
                    onClick={() => void handleResolve(dispute.id)}
                  >
                    Confirm verdict
                  </Button>
                </div>
              ) : null}
            </article>
          ))
        )}
      </div>
    </div>
  );
}
