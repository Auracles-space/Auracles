"use client";

/**
 * Admin project-dispute queue panel.
 *
 * Lists Project milestone disputes across all Projects and lets an admin
 * resolve an active dispute with a release, refund, or split escrow outcome.
 * Resolution is 2FA-gated (TOTP) to match the audited admin escrow controls.
 * Styled as a responsive CSS Grid table that collapses to cards on mobile.
 *
 * Maps to: FR-PROJ-022, BR-PROJ-014.
 */
import { useEffect, useState } from "react";

import { TotpInput } from "@/components/modules/auth/totp-input";
import { Button } from "@/components/ui/button";
import { TableSkeleton } from "@/components/ui/skeletons/table-skeleton";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import {
  listAdminProjectDisputes,
  resolveAdminProjectDispute,
} from "@/lib/generated/sdk.gen";
import type { AdminDisputeResponse } from "@/lib/generated/types.gen";
import { formatLabel, formatMoney } from "@/lib/marketplace/format";

type DisputeStatusFilter = "active" | "resolved";
type ResolutionType = "release" | "refund" | "split";

/**
 * Format one dispute timestamp for compact admin copy.
 *
 * @param value - API timestamp string.
 */
function formatTimestamp(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(parsed);
}

/**
 * Render the project-dispute queue with resolution controls for admins.
 */
export function AdminDisputesPanel() {
  const [disputes, setDisputes] = useState<AdminDisputeResponse[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState<DisputeStatusFilter>("active");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const [resolutionType, setResolutionType] = useState<ResolutionType>("release");
  const [releaseAmount, setReleaseAmount] = useState("");
  const [refundAmount, setRefundAmount] = useState("");
  const [notes, setNotes] = useState("");
  const [totpCode, setTotpCode] = useState("");

  useEffect(() => {
    let mounted = true;

    async function loadDisputes(): Promise<void> {
      setLoading(true);
      configureBrowserClient();
      const result = await listAdminProjectDisputes({
        headers: getAccessTokenHeaders(),
        query: statusFilter === "resolved" ? { status: "resolved" } : {},
      });

      if (!mounted) {
        return;
      }

      setLoading(false);
      if (!result.response.ok || !result.data) {
        setError(describeGeneratedError(result.error));
        return;
      }

      setError(null);
      setDisputes(result.data.disputes);
    }

    void loadDisputes();
    return () => {
      mounted = false;
    };
  }, [statusFilter]);

  /**
   * Reset the inline resolution form to its defaults.
   */
  function resetForm(): void {
    setSelectedId(null);
    setResolutionType("release");
    setReleaseAmount("");
    setRefundAmount("");
    setNotes("");
    setTotpCode("");
  }

  /**
   * Open the resolution form for one dispute, prefilling the release amount with
   * the full held escrow so the common "release in full" case is one click.
   *
   * @param dispute - The dispute being resolved.
   */
  function startResolve(dispute: AdminDisputeResponse): void {
    setSelectedId(dispute.id);
    setResolutionType("release");
    setReleaseAmount(dispute.escrow_amount ?? "");
    setRefundAmount("");
    setNotes("");
    setTotpCode("");
  }

  const splitInvalid =
    resolutionType === "split" &&
    (releaseAmount.trim().length === 0 || refundAmount.trim().length === 0);
  const canResolve =
    !pending && notes.trim().length > 0 && totpCode.trim().length >= 6 && !splitInvalid;

  async function handleResolve(disputeId: string): Promise<void> {
    setPending(true);
    setError(null);
    configureBrowserClient();
    const result = await resolveAdminProjectDispute({
      body: {
        resolution_type: resolutionType,
        release_amount: resolutionType === "refund" ? null : releaseAmount.trim() || null,
        refund_amount: resolutionType === "release" ? null : refundAmount.trim() || null,
        resolution_notes: notes.trim(),
        totp_code: totpCode.trim(),
      },
      headers: getAccessTokenHeaders(),
      path: { dispute_id: disputeId },
    });
    setPending(false);

    if (!result.response.ok || !result.data) {
      setError(describeGeneratedError(result.error));
      return;
    }

    // Resolving removes the dispute from the active queue; refresh by dropping it.
    setDisputes((current) =>
      current ? current.filter((row) => row.id !== disputeId) : current,
    );
    resetForm();
  }

  if (loading && disputes === null) {
    return <TableSkeleton />;
  }

  const rows = disputes ?? [];

  return (
    <section className="grid gap-6">
      <header className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
        <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
          Admin disputes
        </p>
        <h2 className="mt-2 font-heading text-3xl font-bold text-foreground">
          Project disputes
        </h2>
        <p className="mt-3 max-w-3xl text-sm leading-6 text-foreground-muted">
          Review milestone disputes raised in Project workspaces and resolve them
          with a release, refund, or split escrow outcome. Resolution requires 2FA.
        </p>
      </header>

      <nav
        aria-label="Filter disputes by status"
        className="flex flex-wrap gap-1 rounded-2xl border border-border-default bg-surface-1 p-1.5 shadow-sm max-w-xs"
      >
        {(["active", "resolved"] as const).map((value) => {
          const isActive = statusFilter === value;
          return (
            <button
              aria-pressed={isActive}
              className={[
                "flex-1 min-h-11 rounded-xl px-4 text-sm font-semibold transition-all outline-none focus-visible:ring-2 focus-visible:ring-accent",
                isActive
                  ? "bg-foreground text-background shadow-sm"
                  : "text-foreground-muted hover:bg-surface-2 hover:text-foreground",
              ].join(" ")}
              key={value}
              onClick={() => {
                resetForm();
                setStatusFilter(value);
              }}
              type="button"
            >
              {value === "active" ? "Active" : "Resolved"}
            </button>
          );
        })}
      </nav>

      {error ? (
        <div className="rounded-2xl border border-error/30 bg-error/10 p-4 text-sm text-error">
          {error}
        </div>
      ) : null}

      {rows.length === 0 ? (
        <div className="rounded-2xl border border-border-default bg-surface-1 p-8 text-center text-sm text-foreground-muted">
          {statusFilter === "active"
            ? "No active disputes. Raised disputes will appear here for resolution."
            : "No resolved disputes yet."}
        </div>
      ) : (
        <div className="grid gap-4 md:gap-0 md:divide-y md:divide-border-default/40 md:rounded-2xl md:border md:border-border-default md:bg-surface-1 md:shadow-sm overflow-hidden">
          {/* Table Header - Only visible on desktop/tablet */}
          <div className="hidden md:grid md:grid-cols-[0.8fr_1fr_1.5fr_1fr_1.2fr] md:gap-4 md:bg-surface-2/40 md:p-4 md:pl-6 md:pr-6 text-xs font-semibold uppercase tracking-wider text-foreground-muted select-none">
            <div>Status</div>
            <div>Project</div>
            <div>Reason</div>
            <div>Raised</div>
            <div className="text-right">Actions / Outcome</div>
          </div>

          {rows.map((dispute) => {
            const isSelected = selectedId === dispute.id;
            const isResolved = dispute.status === "resolved";
            return (
              <article
                aria-label={`Dispute ${dispute.id.slice(0, 8)}`}
                className={`
                  transition-colors flex flex-col
                  /* Mobile Card styles */
                  rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm gap-3
                  /* Desktop/Tablet Table row styles */
                  md:grid md:grid-cols-[0.8fr_1fr_1.5fr_1fr_1.2fr] md:items-center md:gap-4
                  md:rounded-none md:border-none md:bg-transparent md:p-4 md:pl-6 md:pr-6 md:shadow-none
                  ${isSelected ? "md:bg-surface-2/50" : "md:hover:bg-surface-2/30"}
                `}
                key={dispute.id}
                role="article"
              >
                {/* Column 1: Status */}
                <div>
                  <span className="md:hidden text-xs text-foreground-muted block mb-1 font-semibold uppercase tracking-wider">Status</span>
                  <span
                    className={[
                      "inline-flex items-center rounded-badge border px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wider",
                      isResolved
                        ? "border-success/30 bg-success/10 text-success"
                        : "border-warning/30 bg-warning/10 text-warning",
                    ].join(" ")}
                  >
                    {formatLabel(dispute.status)}
                  </span>
                </div>

                {/* Column 2: Project, milestone, and money at stake */}
                <div className="grid gap-0.5">
                  <span className="md:hidden text-xs text-foreground-muted block mb-1 font-semibold uppercase tracking-wider">Project</span>
                  <a
                    className="text-sm font-semibold text-accent hover:underline md:text-xs"
                    href={`/projects/${dispute.project_id}`}
                  >
                    {dispute.project_title}
                  </a>
                  <span className="text-xs text-foreground-muted">
                    {dispute.milestone_name}
                  </span>
                  <span className="text-xs font-semibold text-foreground">
                    Escrow{" "}
                    {dispute.escrow_amount
                      ? formatMoney(dispute.escrow_amount, dispute.currency)
                      : "—"}
                    {dispute.escrow_status ? (
                      <span className="font-normal text-foreground-muted">
                        {" "}
                        ({formatLabel(dispute.escrow_status)})
                      </span>
                    ) : null}
                  </span>
                </div>

                {/* Column 3: Dispute Reason */}
                <div className="text-sm text-foreground md:text-xs leading-relaxed max-h-32 overflow-y-auto" title={dispute.reason}>
                  <span className="md:hidden text-xs text-foreground-muted block mb-1 font-semibold uppercase tracking-wider">Reason</span>
                  <p className="whitespace-pre-wrap">{dispute.reason}</p>
                </div>

                {/* Column 4: Parties, who raised it, and when */}
                <div className="text-sm text-foreground md:text-xs">
                  <span className="md:hidden text-xs text-foreground-muted block mb-1 font-semibold uppercase tracking-wider">Parties</span>
                  <span className="block">
                    <span className="text-foreground-muted">Operator:</span>{" "}
                    {dispute.operator_name}
                  </span>
                  <span className="block">
                    <span className="text-foreground-muted">Contributor:</span>{" "}
                    {dispute.contributor_name}
                  </span>
                  <span className="mt-1 block text-foreground-muted">
                    Raised by {dispute.raised_by_name} ({formatLabel(dispute.raised_by_role)}) ·{" "}
                    {formatTimestamp(dispute.created_at)}
                  </span>
                </div>

                {/* Column 5: Action Button or Resolved Outcome */}
                <div className="md:text-right">
                  {isResolved ? (
                    <div className="text-xs text-foreground-muted leading-relaxed">
                      <span className="md:hidden text-xs text-foreground-muted block mb-1 font-semibold uppercase tracking-wider">Outcome</span>
                      <span className="font-semibold block text-foreground md:text-xs">
                        {formatLabel(dispute.resolution_type || "")}
                      </span>
                      {dispute.resolved_at && (
                        <span className="block text-[10px]">
                          {formatTimestamp(dispute.resolved_at)}
                        </span>
                      )}
                    </div>
                  ) : isSelected ? (
                    <Button disabled className="min-h-10 px-4">Resolving...</Button>
                  ) : (
                    <Button onClick={() => startResolve(dispute)} className="min-h-10 px-4">
                      Resolve dispute
                    </Button>
                  )}
                </div>

                {/* Expandable Outcome Details / Form */}
                {isResolved && dispute.resolution_notes ? (
                  <div className="mt-2 rounded-xl bg-surface-2 p-3 border border-border-default/50 col-span-full text-xs text-foreground-muted text-left">
                    <span className="font-semibold text-foreground block mb-1">Resolution Notes:</span>
                    <p>{dispute.resolution_notes}</p>
                  </div>
                ) : null}

                {isSelected && !isResolved ? (
                  <div className="mt-4 grid gap-4 rounded-xl border border-border-default bg-surface-2 p-4 col-span-full text-left">
                    <h4 className="font-heading text-sm font-bold text-foreground">
                      Resolve Project Dispute
                    </h4>
                    <dl className="grid grid-cols-2 gap-3 rounded-xl border border-border-default bg-background p-3 text-xs sm:grid-cols-4">
                      <div>
                        <dt className="text-foreground-muted">Milestone budget</dt>
                        <dd className="mt-0.5 font-semibold text-foreground">
                          {formatMoney(dispute.milestone_budget, dispute.currency)}
                        </dd>
                      </div>
                      <div>
                        <dt className="text-foreground-muted">Escrow held</dt>
                        <dd className="mt-0.5 font-semibold text-foreground">
                          {dispute.escrow_amount
                            ? formatMoney(dispute.escrow_amount, dispute.currency)
                            : "—"}
                        </dd>
                      </div>
                      <div>
                        <dt className="text-foreground-muted">Operator</dt>
                        <dd className="mt-0.5 font-semibold text-foreground">
                          {dispute.operator_name}
                          {dispute.raised_by_role === "operator" ? (
                            <span className="ml-1 text-[10px] font-bold uppercase text-warning">
                              raised
                            </span>
                          ) : null}
                        </dd>
                      </div>
                      <div>
                        <dt className="text-foreground-muted">Contributor</dt>
                        <dd className="mt-0.5 font-semibold text-foreground">
                          {dispute.contributor_name}
                          {dispute.raised_by_role === "contributor" ? (
                            <span className="ml-1 text-[10px] font-bold uppercase text-warning">
                              raised
                            </span>
                          ) : null}
                        </dd>
                      </div>
                    </dl>
                    <p className="text-xs text-foreground-muted leading-relaxed max-w-2xl">
                      Release and refund amounts must come out of the held escrow.
                      Write resolution notes for the audit trail, then verify with
                      your admin TOTP authenticator code.
                    </p>
                    
                    <div className="grid gap-4 md:grid-cols-2">
                      <label className="grid gap-2 text-sm font-semibold text-foreground">
                        Outcome
                        <select
                          className="min-h-12 rounded-xl border border-border-default bg-background px-4 text-sm text-foreground outline-none transition-colors focus-visible:ring-2 focus-visible:ring-accent"
                          onChange={(event) =>
                            setResolutionType(event.target.value as ResolutionType)
                          }
                          value={resolutionType}
                        >
                          <option value="release">Release to Contributor</option>
                          <option value="refund">Refund to Operator</option>
                          <option value="split">Split Escrow Funds</option>
                        </select>
                      </label>

                      {resolutionType !== "refund" ? (
                        <label className="grid gap-2 text-sm font-semibold text-foreground">
                          Release amount ($)
                          <input
                            className="min-h-12 rounded-xl border border-border-default bg-background px-4 text-sm text-foreground outline-none transition-colors focus-visible:ring-2 focus-visible:ring-accent"
                            inputMode="decimal"
                            onChange={(event) => setReleaseAmount(event.target.value)}
                            placeholder="e.g. 900.00"
                            value={releaseAmount}
                          />
                        </label>
                      ) : null}

                      {resolutionType !== "release" ? (
                        <label className="grid gap-2 text-sm font-semibold text-foreground">
                          Refund amount ($)
                          <input
                            className="min-h-12 rounded-xl border border-border-default bg-background px-4 text-sm text-foreground outline-none transition-colors focus-visible:ring-2 focus-visible:ring-accent"
                            inputMode="decimal"
                            onChange={(event) => setRefundAmount(event.target.value)}
                            placeholder="e.g. 600.00"
                            value={refundAmount}
                          />
                        </label>
                      ) : null}
                    </div>

                    <label className="grid gap-2 text-sm font-semibold text-foreground">
                      Resolution notes
                      <textarea
                        className="min-h-24 rounded-xl border border-border-default bg-background px-4 py-3 text-sm text-foreground outline-none transition-colors focus-visible:ring-2 focus-visible:ring-accent"
                        onChange={(event) => setNotes(event.target.value)}
                        placeholder="Audit log details for this resolution..."
                        value={notes}
                      />
                    </label>

                    <TotpInput onChange={setTotpCode} value={totpCode} />

                    <div className="flex flex-wrap gap-3">
                      <Button
                        disabled={!canResolve}
                        onClick={() => void handleResolve(dispute.id)}
                      >
                        Confirm resolution
                      </Button>
                      <Button onClick={resetForm} variant="secondary">
                        Cancel
                      </Button>
                    </div>
                  </div>
                ) : null}
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
}
