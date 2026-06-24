"use client";

/**
 * Admin Framework directory panel.
 *
 * Lists published Frameworks with their owning Contributor and lets an admin
 * delist (suspend) an arbitrary one with a reason — not only signal-flagged
 * Frameworks surfaced by the moderation queue. Relisting a takedown lives in
 * the suspended-Frameworks panel. Styled as a responsive grid that reads as a
 * table on desktop and a card stack on mobile, matching the user directory.
 */
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { TableSkeleton } from "@/components/ui/skeletons/table-skeleton";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import {
  listAdminFrameworksV1AdminFrameworksGet,
  suspendFrameworkV1AdminFrameworksFrameworkIdSuspendPost,
} from "@/lib/generated/sdk.gen";
import type { AdminFrameworkDirectoryResponse } from "@/lib/generated/types.gen";

/**
 * Format a publication timestamp for compact admin copy.
 *
 * @param value - API timestamp string, or null when never published.
 */
function formatTimestamp(value: string | null | undefined): string {
  if (!value) {
    return "—";
  }
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
 * Render the searchable published-Framework directory with delist controls.
 */
export function AdminFrameworkDirectoryPanel() {
  const [directory, setDirectory] =
    useState<AdminFrameworkDirectoryResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");
  const [selectedFrameworkId, setSelectedFrameworkId] = useState<string | null>(
    null,
  );
  const [reason, setReason] = useState("");
  const [delisting, setDelisting] = useState(false);

  useEffect(() => {
    let mounted = true;

    async function loadFrameworks(): Promise<void> {
      configureBrowserClient();
      const result = await listAdminFrameworksV1AdminFrameworksGet({
        headers: getAccessTokenHeaders(),
        query: { query: query.trim() || undefined },
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

    void loadFrameworks();
    return () => {
      mounted = false;
    };
  }, [query]);

  async function handleDelist(frameworkId: string): Promise<void> {
    setDelisting(true);
    setError(null);
    configureBrowserClient();
    const result = await suspendFrameworkV1AdminFrameworksFrameworkIdSuspendPost({
      body: { reason: reason.trim() },
      headers: getAccessTokenHeaders(),
      path: { framework_id: frameworkId },
    });
    setDelisting(false);

    if (!result.response.ok || !result.data) {
      setError(describeGeneratedError(result.error));
      return;
    }

    // Delisted Frameworks leave the published directory; drop the row.
    setDirectory((current) =>
      current
        ? {
            ...current,
            items: current.items.filter(
              (item) => item.framework_id !== frameworkId,
            ),
          }
        : current,
    );
    setReason("");
    setSelectedFrameworkId(null);
  }

  if (loading) {
    return <TableSkeleton />;
  }

  return (
    <section className="grid gap-6">
      <header className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
        <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
          Published Frameworks
        </p>
        <h2 className="mt-2 font-heading text-3xl font-bold text-foreground">
          Framework controls
        </h2>
        <p className="mt-3 max-w-3xl text-sm leading-6 text-foreground-muted">
          Search any published Framework and delist it with a reason. Reinstate
          a takedown from the suspended Frameworks list below.
        </p>
      </header>

      <section className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
        <label className="grid gap-2 text-sm font-semibold text-foreground">
          Search Frameworks
          <input
            className="min-h-12 rounded-xl border border-border-default bg-background px-4 text-sm text-foreground outline-none transition-colors focus-visible:ring-2 focus-visible:ring-accent"
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search by Framework title"
            value={query}
          />
        </label>
      </section>

      {error ? (
        <div className="rounded-2xl border border-error/30 bg-error/10 p-4 text-sm text-error">
          {error}
        </div>
      ) : null}

      {(directory?.items.length ?? 0) === 0 ? (
        <div className="rounded-2xl border border-border-default bg-surface-1 p-6 text-sm text-foreground-muted">
          No published Frameworks match this search.
        </div>
      ) : (
        <div className="grid gap-4 md:gap-0 md:divide-y md:divide-border-default/40 md:rounded-2xl md:border md:border-border-default md:bg-surface-1 md:shadow-sm overflow-hidden">
          {/* Table header — desktop/tablet only */}
          <div className="hidden md:grid md:grid-cols-[1.6fr_1.2fr_1fr_1fr] md:gap-4 md:bg-surface-2/40 md:p-4 md:pl-6 md:pr-6 text-xs font-semibold uppercase tracking-wider text-foreground-muted select-none">
            <div>Framework</div>
            <div>Contributor</div>
            <div>Published</div>
            <div className="text-right">Actions</div>
          </div>

          {(directory?.items ?? []).map((item) => {
            const isSelected = selectedFrameworkId === item.framework_id;
            return (
              <article
                aria-label={item.title}
                className={`
                  transition-colors flex flex-col
                  rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm gap-3
                  md:grid md:grid-cols-[1.6fr_1.2fr_1fr_1fr] md:items-center md:gap-4
                  md:rounded-none md:border-none md:bg-transparent md:p-4 md:pl-6 md:pr-6 md:shadow-none
                  ${isSelected ? "md:bg-surface-2/50" : "md:hover:bg-surface-2/30"}
                `}
                key={item.framework_id}
              >
                {/* Framework title cell */}
                <div className="grid gap-0.5">
                  <h3 className="font-heading text-lg font-bold text-foreground md:text-sm md:font-semibold">
                    {item.title}
                  </h3>
                  <span className="inline-flex w-fit items-center rounded-badge border border-success/30 bg-success/10 px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wider text-success">
                    {item.status}
                  </span>
                </div>

                {/* Contributor cell */}
                <div className="text-sm text-foreground md:text-xs">
                  <span className="md:hidden text-xs text-foreground-muted block mb-1 font-semibold uppercase tracking-wider">
                    Contributor
                  </span>
                  <span>{item.contributor_name}</span>
                </div>

                {/* Published date cell */}
                <div className="text-sm text-foreground md:text-xs">
                  <span className="md:hidden text-xs text-foreground-muted block mb-1 font-semibold uppercase tracking-wider">
                    Published
                  </span>
                  <span>{formatTimestamp(item.published_at)}</span>
                </div>

                {/* Action cell */}
                <div className="md:text-right">
                  <Button
                    className="min-h-10 px-4"
                    onClick={() => {
                      setReason("");
                      setSelectedFrameworkId(item.framework_id);
                    }}
                    variant="destructive"
                  >
                    Delist
                  </Button>
                </div>

                {/* Expandable delist form */}
                {isSelected ? (
                  <div className="mt-4 grid gap-4 rounded-xl border border-border-default bg-surface-2 p-4 col-span-full text-left">
                    <label className="grid gap-2 text-sm font-semibold text-foreground">
                      Reason
                      <textarea
                        className="min-h-28 rounded-xl border border-border-default bg-background px-4 py-3 text-sm text-foreground outline-none transition-colors focus-visible:ring-2 focus-visible:ring-accent"
                        onChange={(event) => setReason(event.target.value)}
                        placeholder="Why is this Framework being delisted?"
                        value={reason}
                      />
                    </label>
                    <div className="flex flex-wrap gap-3">
                      <Button
                        disabled={delisting || reason.trim().length === 0}
                        onClick={() => void handleDelist(item.framework_id)}
                        variant="destructive"
                      >
                        Confirm delist
                      </Button>
                      <Button
                        onClick={() => {
                          setReason("");
                          setSelectedFrameworkId(null);
                        }}
                        variant="secondary"
                      >
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
