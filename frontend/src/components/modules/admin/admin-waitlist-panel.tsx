"use client";

/**
 * Admin waitlist oversight panel.
 *
 * Read-only: administrators list and search pre-launch waitlist signups to
 * gauge demand and prepare launch invitations. Renders as a table on desktop
 * and stacked cards on mobile.
 *
 * Maps to: admin pre-launch waitlist oversight.
 */
import { useEffect, useState } from "react";

import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import { listAdminWaitlistV1AdminWaitlistGet } from "@/lib/generated/sdk.gen";
import { TableSkeleton } from "@/components/ui/skeletons/table-skeleton";
import type { AdminWaitlistResponse } from "@/lib/generated/types.gen";

/**
 * Format a signup timestamp for compact admin copy.
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
 * Render the read-only admin waitlist directory with email search.
 */
export function AdminWaitlistPanel() {
  const [directory, setDirectory] = useState<AdminWaitlistResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");

  useEffect(() => {
    let mounted = true;

    async function loadWaitlist(): Promise<void> {
      configureBrowserClient();
      const result = await listAdminWaitlistV1AdminWaitlistGet({
        headers: getAccessTokenHeaders(),
        query: {
          page: 1,
          page_size: 20,
          query: query.trim() || undefined,
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
      setDirectory(result.data);
    }

    void loadWaitlist();
    return () => {
      mounted = false;
    };
  }, [query]);

  if (loading) {
    return <TableSkeleton />;
  }

  const items = directory?.items ?? [];

  return (
    <section className="grid gap-6">
      <header className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
        <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
          Admin waitlist
        </p>
        <h2 className="mt-2 font-heading text-3xl font-bold text-foreground">
          Pre-launch signups
        </h2>
        <p className="mt-3 max-w-3xl text-sm leading-6 text-foreground-muted">
          Review pre-launch waitlist signups and their origin. Read-only —
          search by email to find a specific signup.
          {directory ? ` ${directory.total} total.` : ""}
        </p>
      </header>

      <section className="grid gap-4 rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm md:max-w-md">
        <label className="grid gap-2 text-sm font-semibold text-foreground">
          Search email
          <input
            className="min-h-12 rounded-xl border border-border-default bg-background px-4 text-sm text-foreground outline-none transition-colors focus-visible:ring-2 focus-visible:ring-accent"
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search by email address"
            value={query}
          />
        </label>
      </section>

      {error ? (
        <div className="rounded-2xl border border-error/30 bg-error/10 p-4 text-sm text-error">
          {error}
        </div>
      ) : null}

      {items.length === 0 ? (
        <div className="rounded-2xl border border-border-default bg-surface-1 p-8 text-center text-sm text-foreground-muted shadow-sm">
          No waitlist signups match this search.
        </div>
      ) : (
        <div className="grid gap-4 md:gap-0 md:divide-y md:divide-border-default/40 md:rounded-2xl md:border md:border-border-default md:bg-surface-1 md:shadow-sm overflow-hidden">
          <div className="hidden md:grid md:grid-cols-[1.8fr_0.8fr_1.1fr] md:gap-4 md:bg-surface-2/40 md:p-4 md:pl-6 md:pr-6 text-xs font-semibold uppercase tracking-wider text-foreground-muted select-none">
            <div>Email</div>
            <div>Source</div>
            <div className="text-right">Joined</div>
          </div>

          {items.map((item) => (
            <article
              className="
                flex flex-col gap-3 rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm
                md:grid md:grid-cols-[1.8fr_0.8fr_1.1fr] md:items-center md:gap-4
                md:rounded-none md:border-none md:bg-transparent md:p-4 md:pl-6 md:pr-6 md:shadow-none
                md:hover:bg-surface-2/30 transition-colors
              "
              key={item.entry_id}
              role="article"
            >
              <p className="text-sm font-semibold text-foreground break-all md:font-medium">
                {item.email}
              </p>

              <div>
                <span className="md:hidden text-xs text-foreground-muted block mb-1 font-semibold uppercase tracking-wider">
                  Source
                </span>
                {item.source ? (
                  <span className="inline-flex items-center rounded-md border border-border-default bg-surface-2 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-foreground-muted">
                    {item.source}
                  </span>
                ) : (
                  <span className="text-xs text-foreground-subtle">—</span>
                )}
              </div>

              <div className="text-sm text-foreground md:text-right md:text-xs">
                <span className="md:hidden text-xs text-foreground-muted block mb-1 font-semibold uppercase tracking-wider">
                  Joined
                </span>
                {formatTimestamp(item.created_at)}
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
