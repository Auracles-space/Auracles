"use client";

/**
 * Admin project-dispute queue panel.
 *
 * Lists Project milestone disputes across all Projects and lets an admin
 * resolve an active dispute with a release, refund, or split escrow outcome.
 * Resolution is 2FA-gated (TOTP) to match the audited admin escrow controls.
 * Styled as a responsive card list that reads as a table on desktop.
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
import type { DisputeResponse } from "@/lib/generated/types.gen";
import { formatLabel } from "@/lib/marketplace/format";

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
  const [disputes, setDisputes] = useState<DisputeResponse[] | null>(null);
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

      <div className="flex flex-wrap gap-2">
        {(["active", "resolved"] as const).map((value) => (
          <button
            className={[
              "min-h-11 rounded-xl border px-4 text-sm font-semibold transition-colors",
              statusFilter === value
                ? "border-accent bg-accent/10 text-accent"
                : "border-border-default bg-surface-1 text-foreground-muted hover:bg-surface-2/40",
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
        ))}
      </div>

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
      ) : null}

      <div className="grid gap-4">
        {rows.map((dispute) => {
          const isSelected = selectedId === dispute.id;
          const isResolved = dispute.status === "resolved";
          return (
            <article
              className="grid gap-3 rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm"
              key={dispute.id}
            >
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="grid gap-1">
                  <span
                    className={[
                      "inline-flex w-fit items-center rounded-badge border px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wider",
                      isResolved
                        ? "border-success/30 bg-success/10 text-success"
                        : "border-warning/30 bg-warning/10 text-warning",
                    ].join(" ")}
                  >
                    {formatLabel(dispute.status)}
                  </span>
                  <p className="text-sm leading-6 text-foreground">{dispute.reason}</p>
                  <p className="text-xs text-foreground-muted">
                    Raised {formatTimestamp(dispute.created_at)} · Milestone{" "}
                    <span className="font-mono">{dispute.milestone_id.slice(0, 8)}</span>
                  </p>
                </div>
                <a
                  className="text-sm font-semibold text-accent hover:underline"
                  href={`/projects/${dispute.project_id}`}
                >
                  Open project
                </a>
              </div>

              {isResolved ? (
                <p className="text-xs text-foreground-muted">
                  Resolved {dispute.resolved_at ? formatTimestamp(dispute.resolved_at) : ""}
                  {dispute.resolution_type
                    ? ` · ${formatLabel(dispute.resolution_type)}`
                    : ""}
                  {dispute.resolution_notes ? ` — ${dispute.resolution_notes}` : ""}
                </p>
              ) : isSelected ? (
                <div className="grid gap-4 rounded-xl border border-border-default bg-surface-2 p-4">
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
                      <option value="split">Split</option>
                    </select>
                  </label>

                  {resolutionType !== "refund" ? (
                    <label className="grid gap-2 text-sm font-semibold text-foreground">
                      Release amount
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
                      Refund amount
                      <input
                        className="min-h-12 rounded-xl border border-border-default bg-background px-4 text-sm text-foreground outline-none transition-colors focus-visible:ring-2 focus-visible:ring-accent"
                        inputMode="decimal"
                        onChange={(event) => setRefundAmount(event.target.value)}
                        placeholder="e.g. 600.00"
                        value={refundAmount}
                      />
                    </label>
                  ) : null}

                  <label className="grid gap-2 text-sm font-semibold text-foreground">
                    Resolution notes
                    <textarea
                      className="min-h-24 rounded-xl border border-border-default bg-background px-4 py-3 text-sm text-foreground outline-none transition-colors focus-visible:ring-2 focus-visible:ring-accent"
                      onChange={(event) => setNotes(event.target.value)}
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
              ) : (
                <div>
                  <Button onClick={() => setSelectedId(dispute.id)}>
                    Resolve dispute
                  </Button>
                </div>
              )}
            </article>
          );
        })}
      </div>
    </section>
  );
}
