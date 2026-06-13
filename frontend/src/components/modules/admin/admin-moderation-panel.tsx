"use client";

/**
 * Admin moderation queue panel.
 *
 * Renders the aggregated moderation queue from the admin API and exposes a
 * simple queue-type filter so operators can focus on one signal class.
 */
import { useEffect, useState } from "react";

import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import { listModerationQueueV1AdminModerationQueueGet } from "@/lib/generated/sdk.gen";
import type { AdminModerationQueueResponse } from "@/lib/generated/types.gen";
import { formatLabel } from "@/lib/marketplace/format";

type QueueType = "all" | "near_duplicate_block" | "pii_review" | "rarity_review";

const pageSize = 20;

/**
 * Render the admin moderation queue.
 */
export function AdminModerationPanel() {
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [queue, setQueue] = useState<AdminModerationQueueResponse | null>(null);
  const [queueType, setQueueType] = useState<QueueType>("all");

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

  if (loading) {
    return <p className="text-sm text-foreground-muted">Loading moderation queue.</p>;
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
            onChange={(event) => setQueueType(event.target.value as QueueType)}
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
          return (
            <article
              className="rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm"
              key={item.signal_id}
            >
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
                    {formatLabel(item.queue_type)}
                  </p>
                  <h3 className="mt-1 font-heading text-xl font-bold text-foreground">
                    {item.framework_title}
                  </h3>
                  <p className="mt-1 text-sm text-foreground-muted">
                    Contributor: {item.contributor_name}
                  </p>
                </div>
                <p className="text-sm text-foreground-muted">{item.signal_at}</p>
              </div>

              {item.artifact_name ? (
                <p className="mt-4 text-sm text-foreground">
                  Artifact: <span className="font-medium">{item.artifact_name}</span>
                </p>
              ) : null}

              <div className="mt-4 rounded-xl border border-border-default bg-surface-2 p-4">
                <pre className="overflow-x-auto whitespace-pre-wrap text-xs text-foreground-muted">
                  {JSON.stringify(item.details, null, 2)}
                </pre>
              </div>

              <div className="mt-4 flex flex-wrap gap-2">
                {item.action_links
                  .filter((link) => link.actor_role === "admin")
                  .map((link) => (
                    <span
                      className="rounded-md border border-border-default bg-background px-3 py-2 text-xs text-foreground"
                      key={`${item.signal_id}:${link.rel}`}
                    >
                      {link.method} {link.path}
                    </span>
                  ))}
              </div>

              {contributorFollowUp ? (
                <p className="mt-4 text-sm font-medium text-warning">
                  Contributor follow-up required
                </p>
              ) : null}
            </article>
          );
        })}
      </div>
    </section>
  );
}
