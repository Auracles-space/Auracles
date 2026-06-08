"use client";

/**
 * Contributor Framework list.
 *
 * Fetches owned Framework summaries through the generated client using the
 * in-memory access token.
 */
import Link from "next/link";
import { useEffect, useState } from "react";

import { listContributorFrameworks } from "@/lib/generated/sdk.gen";
import type { FrameworkListItem } from "@/lib/generated/types.gen";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import { formatLabel, formatMoney } from "@/lib/marketplace/format";

/**
 * Render Contributor-owned Framework summaries.
 */
export function FrameworkList() {
  const [frameworks, setFrameworks] = useState<FrameworkListItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function loadFrameworks() {
      try {
        configureBrowserClient();
        const result = await listContributorFrameworks({
          headers: getAccessTokenHeaders(),
        });
        if (!result.response.ok || !result.data) {
          setError(describeGeneratedError(result.error));
          setLoading(false);
          return;
        }
        setFrameworks(result.data);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Network error or API unavailable.");
      } finally {
        setLoading(false);
      }
    }

    void loadFrameworks();
  }, []);

  if (loading) {
    return <p className="text-sm text-foreground-muted">Loading frameworks.</p>;
  }

  if (error) {
    return <p className="text-sm text-error">{error}</p>;
  }

  if (frameworks.length === 0) {
    return (
      <div className="rounded-[8px] border border-border-default bg-surface-2 p-8 text-center">
        <h2 className="font-heading text-xl font-bold text-foreground">
          No frameworks yet
        </h2>
        <p className="mt-2 text-sm text-foreground-muted">
          Create your first draft to begin upload and processing.
        </p>
      </div>
    );
  }

  return (
    <div className="grid gap-4">
      {frameworks.map((framework) => (
        <article
          className="rounded-[8px] border border-border-default bg-surface-2 p-5"
          key={framework.id}
        >
          <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
                {formatLabel(framework.status)}
              </p>
              <h2 className="mt-1 font-heading text-xl font-bold text-foreground">
                {framework.title}
              </h2>
              <p className="mt-2 text-sm text-foreground-muted">
                {formatLabel(framework.category)} · Version {framework.version} ·{" "}
                {formatMoney(framework.price, framework.currency)}
              </p>
            </div>
            <Link
              className="inline-flex min-h-11 items-center justify-center rounded-[6px] bg-foreground px-4 py-2 text-sm font-semibold text-background transition hover:bg-foreground/90"
              href={`/dashboard/frameworks/${framework.id}`}
            >
              Open
            </Link>
          </div>
        </article>
      ))}
    </div>
  );
}
