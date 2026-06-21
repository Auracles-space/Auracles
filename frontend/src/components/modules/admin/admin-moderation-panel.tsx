"use client";

/**
 * Admin moderation queue panel.
 *
 * Renders the aggregated moderation queue from the admin API and exposes a
 * signal-type filter. Enables interactive framework suspension and duplication
 * overrides directly from the queue.
 */
import { useEffect, useState } from "react";

import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import {
  listModerationQueueV1AdminModerationQueueGet,
  overrideRarityBlockV1AdminFrameworksFrameworkIdRarityBlockOverridePost,
  suspendFrameworkV1AdminFrameworksFrameworkIdSuspendPost,
} from "@/lib/generated/sdk.gen";
import { TableSkeleton } from "@/components/ui/skeletons/table-skeleton";
import { Button } from "@/components/ui/button";
import type { AdminModerationQueueResponse } from "@/lib/generated/types.gen";
import { formatLabel } from "@/lib/marketplace/format";

type QueueType = "all" | "near_duplicate_block" | "pii_review" | "rarity_review";

const pageSize = 20;

/**
 * Format a timestamp for displaying when the signal was generated.
 *
 * @param value - ISO timestamp string.
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
 * Render the admin moderation queue.
 */
export function AdminModerationPanel() {
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [queue, setQueue] = useState<AdminModerationQueueResponse | null>(null);
  const [queueType, setQueueType] = useState<QueueType>("all");
  const [selectedSignalId, setSelectedSignalId] = useState<string | null>(null);
  const [formAction, setFormAction] = useState<"suspend" | "override" | null>(null);
  const [reason, setReason] = useState("");
  const [busyAction, setBusyAction] = useState(false);

  useEffect(() => {
    let mounted = true;

    async function loadQueue(type: QueueType): Promise<void> {
      configureBrowserClient();
      const result = await listModerationQueueV1AdminModerationQueueGet({
        headers: getAccessTokenHeaders(),
        query: {
          page: 1,
          page_size: pageSize,
          type,
        },
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
      setQueue(result.data);
    }

    void loadQueue(queueType);
    return () => {
      mounted = false;
    };
  }, [queueType]);

  async function handleConfirmOverride(frameworkId: string): Promise<void> {
    setBusyAction(true);
    setError(null);
    configureBrowserClient();
    const result = await overrideRarityBlockV1AdminFrameworksFrameworkIdRarityBlockOverridePost({
      body: { reason: reason.trim() },
      headers: getAccessTokenHeaders(),
      path: { framework_id: frameworkId },
    });
    setBusyAction(false);

    if (!result.response.ok) {
      setError(describeGeneratedError(result.error));
      return;
    }

    // Success: remove signal from queue local list
    setQueue((current) => {
      if (!current) {
        return current;
      }
      return {
        ...current,
        items: current.items.filter((item) => item.framework_id !== frameworkId),
      };
    });
    setSelectedSignalId(null);
    setFormAction(null);
    setReason("");
  }

  async function handleConfirmSuspend(frameworkId: string): Promise<void> {
    setBusyAction(true);
    setError(null);
    configureBrowserClient();
    const result = await suspendFrameworkV1AdminFrameworksFrameworkIdSuspendPost({
      body: { reason: reason.trim() },
      headers: getAccessTokenHeaders(),
      path: { framework_id: frameworkId },
    });
    setBusyAction(false);

    if (!result.response.ok) {
      setError(describeGeneratedError(result.error));
      return;
    }

    // Success: remove signal from queue local list
    setQueue((current) => {
      if (!current) {
        return current;
      }
      return {
        ...current,
        items: current.items.filter((item) => item.framework_id !== frameworkId),
      };
    });
    setSelectedSignalId(null);
    setFormAction(null);
    setReason("");
  }

  if (loading) {
    return <TableSkeleton />;
  }

  return (
    <section className="grid gap-6">
      <header className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
        <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
          Admin moderation
        </p>
        <h2 className="mt-2 font-heading text-3xl font-bold text-foreground">
          Moderation queue
        </h2>
        <p className="mt-3 max-w-3xl text-sm leading-6 text-foreground-muted">
          Review rarity, near-duplicate, and PII signals without switching
          between multiple admin endpoints.
        </p>
      </header>

      <section className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
        <div className="grid gap-2 md:max-w-xs">
          <label className="text-sm font-semibold text-foreground" htmlFor="queue-type">
            Queue type
          </label>
          <select
            className="min-h-12 rounded-xl border border-border-default bg-background px-4 text-sm text-foreground outline-none transition-colors focus-visible:ring-2 focus-visible:ring-accent"
            id="queue-type"
            onChange={(event) => {
              setQueueType(event.target.value as QueueType);
              setSelectedSignalId(null);
              setFormAction(null);
            }}
            value={queueType}
          >
            <option value="all">All signals</option>
            <option value="pii_review">PII review</option>
            <option value="near_duplicate_block">Near-duplicate block</option>
            <option value="rarity_review">Rarity review</option>
          </select>
        </div>
      </section>

      {error ? (
        <div className="rounded-2xl border border-error/30 bg-error/10 p-4 text-sm text-error">
          {error}
        </div>
      ) : null}

      <div className="grid gap-4">
        {(queue?.items ?? []).map((item) => {
          const contributorFollowUp = item.action_links.some(
            (link) => link.actor_role !== "admin",
          );
          const canSuspend = item.action_links.some((l) => l.rel === "suspend_framework");
          const canOverride = item.action_links.some((l) => l.rel === "override_rarity_block");
          const isSelected = selectedSignalId === item.signal_id;

          const details = item.details;
          const isPii = item.queue_type === "pii_review";

          // Calculate similarity metrics for duplicate/rarity rows
          const jaccard = parseFloat((details.internal_jaccard as string) || "0");
          const blended = parseFloat((details.blended_score as string) || "0");
          const jaccardPercent = Math.min(100, Math.round(jaccard * 100));
          const blendedPercent = Math.min(100, Math.round(blended * 100));

          return (
            <article
              className="rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm"
              key={item.signal_id}
            >
              <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border-default/40 pb-4 mb-4">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
                    {formatLabel(item.queue_type)}
                  </p>
                  <h3 className="mt-1 font-heading text-xl font-bold text-foreground">
                    {item.framework_title}
                  </h3>
                  <p className="mt-1 text-sm text-foreground-muted">
                    Contributor: <span className="font-medium text-foreground">{item.contributor_name}</span>
                  </p>
                </div>
                <span className="text-xs font-medium text-foreground-muted">
                  {formatTimestamp(item.signal_at)}
                </span>
              </div>

              {item.artifact_name ? (
                <div className="text-sm text-foreground mb-4">
                  Artifact: <span className="font-semibold text-accent">{item.artifact_name}</span>
                </div>
              ) : null}

              {/* Styled details content depending on queue class */}
              <div className="rounded-xl border border-border-default bg-surface-2 p-4">
                {isPii ? (
                  <div className="grid gap-4">
                    <div>
                      <h4 className="text-xs font-semibold uppercase tracking-[0.05em] text-foreground-muted mb-2">
                        PII Types Detected
                      </h4>
                      <div className="flex flex-wrap gap-1.5">
                        {((details.pii_types_found as string[]) ?? []).map((t) => (
                          <span
                            key={t}
                            className="inline-flex items-center rounded-badge border border-error/20 bg-error/10 px-2.5 py-0.5 text-[10px] font-bold text-error uppercase tracking-wider"
                          >
                            {t}
                          </span>
                        ))}
                        {((details.pii_types_found as string[]) ?? []).length === 0 && (
                          <span className="text-xs text-foreground-muted italic">None specified</span>
                        )}
                      </div>
                    </div>
                    <div className="grid grid-cols-2 gap-4 text-sm border-t border-border-default/40 pt-3">
                      <div>
                        <span className="text-xs text-foreground-muted font-medium">Auto-Redacted</span>
                        <p className="mt-0.5 font-bold text-foreground">
                          {details.auto_redacted ? "Yes" : "No"}
                        </p>
                      </div>
                      <div>
                        <span className="text-xs text-foreground-muted font-medium">Redaction Status</span>
                        <p className="mt-0.5 font-bold text-foreground uppercase tracking-wide text-xs">
                          {details.redaction_status ? formatLabel(details.redaction_status as string) : "Pending"}
                        </p>
                      </div>
                    </div>
                  </div>
                ) : (
                  <div className="grid gap-4">
                    <div className="grid gap-4 sm:grid-cols-2">
                      {jaccard > 0 && (
                        <div>
                          <div className="flex items-center justify-between text-xs font-semibold text-foreground-muted uppercase tracking-[0.05em] mb-1.5">
                            <span>Internal Jaccard Similarity</span>
                            <span className="text-foreground font-mono">{jaccardPercent}%</span>
                          </div>
                          <div className="h-2 w-full bg-surface-3 rounded-full overflow-hidden">
                            <div className="h-full bg-accent transition-all" style={{ width: `${jaccardPercent}%` }} />
                          </div>
                        </div>
                      )}
                      {blended > 0 && (
                        <div>
                          <div className="flex items-center justify-between text-xs font-semibold text-foreground-muted uppercase tracking-[0.05em] mb-1.5">
                            <span>Blended Similarity Score</span>
                            <span className="text-foreground font-mono">{blendedPercent}%</span>
                          </div>
                          <div className="h-2 w-full bg-surface-3 rounded-full overflow-hidden">
                            <div className="h-full bg-accent/80 transition-all" style={{ width: `${blendedPercent}%` }} />
                          </div>
                        </div>
                      )}
                    </div>

                    {/* External matches list */}
                    {!!details.external_phrases_queried &&
                      (details.external_phrases_queried as string[]).length > 0 && (
                        <div className="border-t border-border-default/40 pt-3">
                          <h4 className="text-xs font-semibold uppercase tracking-[0.05em] text-foreground-muted mb-2">
                            External Query Matches
                          </h4>
                          <ul className="grid gap-2 text-sm">
                            {(details.external_phrases_queried as string[]).map((phrase, idx) => {
                              const hitCount = (details.external_hit_counts as number[])?.[idx] ?? 0;
                              return (
                                <li
                                  key={idx}
                                  className="flex justify-between items-center rounded-xl bg-surface-3 px-3 py-2"
                                >
                                  <span className="font-mono text-xs text-foreground truncate max-w-[200px] sm:max-w-md">
                                    "{phrase}"
                                  </span>
                                  <span className="rounded-badge bg-foreground/10 px-2 py-0.5 text-xs font-bold text-foreground">
                                    {hitCount} hit{hitCount !== 1 ? "s" : ""}
                                  </span>
                                </li>
                              );
                            })}
                          </ul>
                        </div>
                      )}

                    {/* Blocked artifact list */}
                    {!!details.blocked_artifact_ids &&
                      (details.blocked_artifact_ids as string[]).length > 0 && (
                        <div className="border-t border-border-default/40 pt-3">
                          <h4 className="text-xs font-semibold uppercase tracking-[0.05em] text-foreground-muted mb-2">
                            Blocked Artifacts
                          </h4>
                          <div className="flex flex-wrap gap-1.5">
                            {(details.blocked_artifact_ids as string[]).map((id) => (
                              <span
                                key={id}
                                className="inline-flex items-center rounded-badge border border-border-default bg-surface-3 px-2 py-0.5 text-[10px] font-mono text-foreground-muted"
                              >
                                {id}
                              </span>
                            ))}
                          </div>
                        </div>
                      )}
                  </div>
                )}
              </div>

              {/* Action Buttons */}
              <div className="mt-4 flex flex-wrap gap-3">
                {canOverride && (
                  <Button
                    onClick={() => {
                      setSelectedSignalId(item.signal_id);
                      setFormAction("override");
                      setReason("");
                    }}
                    className="min-h-10 px-4"
                    variant="secondary"
                  >
                    Override Rarity Block
                  </Button>
                )}
                {canSuspend && (
                  <Button
                    onClick={() => {
                      setSelectedSignalId(item.signal_id);
                      setFormAction("suspend");
                      setReason("");
                    }}
                    className="min-h-10 px-4"
                    variant="destructive"
                  >
                    Suspend Framework
                  </Button>
                )}
                {contributorFollowUp ? (
                  <span className="inline-flex items-center rounded-badge border border-warning/35 bg-warning/10 px-2.5 py-1 text-[10px] font-bold text-warning uppercase tracking-wider">
                    Contributor follow-up required
                  </span>
                ) : null}
              </div>

              {/* Expandable Action Form */}
              {isSelected && formAction && (
                <div className="mt-4 grid gap-4 rounded-xl border border-border-default bg-surface-2 p-4 text-left">
                  <label className="grid gap-2 text-sm font-semibold text-foreground">
                    {formAction === "override" ? "Reason for Override" : "Reason for Suspension"}
                    <textarea
                      className="min-h-24 rounded-xl border border-border-default bg-background px-4 py-3 text-sm text-foreground outline-none transition-colors focus-visible:ring-2 focus-visible:ring-accent"
                      onChange={(event) => setReason(event.target.value)}
                      placeholder={
                        formAction === "override"
                          ? "Explain why this duplication warning is overridden (min 5 characters)..."
                          : "Explain why this framework is being suspended..."
                      }
                      value={reason}
                    />
                  </label>
                  <div className="flex flex-wrap gap-3">
                    {formAction === "override" ? (
                      <Button
                        disabled={busyAction || reason.trim().length < 5}
                        onClick={() => void handleConfirmOverride(item.framework_id)}
                      >
                        Confirm override
                      </Button>
                    ) : (
                      <Button
                        disabled={busyAction || reason.trim().length < 1}
                        onClick={() => void handleConfirmSuspend(item.framework_id)}
                        variant="destructive"
                      >
                        Confirm suspension
                      </Button>
                    )}
                    <Button
                      disabled={busyAction}
                      onClick={() => {
                        setSelectedSignalId(null);
                        setFormAction(null);
                        setReason("");
                      }}
                      variant="secondary"
                    >
                      Cancel
                    </Button>
                  </div>
                </div>
              )}
            </article>
          );
        })}
      </div>
    </section>
  );
}
