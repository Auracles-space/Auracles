"use client";

/**
 * Operator saved-search settings panel.
 *
 * Lists owned Explore saved searches and provides client-side controls for
 * rename, alert toggle, deletion, and opening the current filter snapshot.
 */
import { BellIcon, TrashIcon } from "@radix-ui/react-icons";
import Link from "next/link";
import { useEffect, useState } from "react";

import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import { TableSkeleton } from "@/components/ui/skeletons/table-skeleton";
import {
  deleteSavedSearch,
  listSavedSearches,
  updateSavedSearch,
} from "@/lib/generated/sdk.gen";
import type { SavedSearchResponse } from "@/lib/generated/types.gen";
import { formatLabel } from "@/lib/marketplace/format";
import { savedSearchFiltersToHref } from "@/lib/marketplace/saved-search-filters";

type PendingAction = {
  id: string;
  type: "delete" | "rename" | "toggle";
} | null;

/**
 * Render a filter summary for a saved search.
 *
 * @param filters - Persisted saved-search filter blob.
 */
function FilterTags({ filters }: { filters: Record<string, unknown> }) {
  const entries = Object.entries(filters).filter(
    ([, value]) => value !== null && value !== undefined && value !== "",
  );

  if (entries.length === 0) {
    return (
      <span className="rounded-md border border-border-default bg-surface-2 px-2.5 py-1 text-xs font-medium text-foreground-muted">
        All marketplace items
      </span>
    );
  }

  return (
    <div className="flex flex-wrap gap-2">
      {entries.slice(0, 6).map(([key, value]) => (
        <span
          className="rounded-md border border-border-default bg-surface-2 px-2.5 py-1 text-xs font-medium text-foreground-muted"
          key={key}
        >
          {formatLabel(key)}: {formatLabel(String(value))}
        </span>
      ))}
    </div>
  );
}

/**
 * Render list/edit/delete controls for Operator saved searches.
 */
export function SavedSearchesPanel() {
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState<PendingAction>(null);
  const [savedSearches, setSavedSearches] = useState<SavedSearchResponse[]>([]);
  const [names, setNames] = useState<Record<string, string>>({});

  useEffect(() => {
    let mounted = true;

    async function loadSavedSearches(): Promise<void> {
      configureBrowserClient();
      const result = await listSavedSearches({
        headers: getAccessTokenHeaders(),
      });

      if (!mounted) {
        return;
      }

      setLoading(false);
      if (!result.response.ok) {
        setError(describeGeneratedError(result.error));
        return;
      }

      const rows: SavedSearchResponse[] = result.data?.saved_searches ?? [];
      setSavedSearches(rows);
      setNames(
        Object.fromEntries(rows.map((savedSearch) => [savedSearch.id, savedSearch.name])),
      );
    }

    void loadSavedSearches();
    return () => {
      mounted = false;
    };
  }, []);

  async function renameSavedSearch(savedSearch: SavedSearchResponse): Promise<void> {
    const nextName = names[savedSearch.id]?.trim();
    if (!nextName) {
      setError("Enter a saved search name.");
      return;
    }

    setPending({ id: savedSearch.id, type: "rename" });
    configureBrowserClient();
    const result = await updateSavedSearch({
      body: { name: nextName },
      headers: getAccessTokenHeaders(),
      path: { saved_search_id: savedSearch.id },
    });
    setPending(null);

    if (!result.response.ok || !result.data) {
      setError(describeGeneratedError(result.error));
      return;
    }

    setError(null);
    setSavedSearches((current) =>
      current.map((row) => (row.id === savedSearch.id ? result.data : row)),
    );
  }

  async function toggleAlerts(savedSearch: SavedSearchResponse): Promise<void> {
    setPending({ id: savedSearch.id, type: "toggle" });
    configureBrowserClient();
    const result = await updateSavedSearch({
      body: { alert_enabled: !savedSearch.alert_enabled },
      headers: getAccessTokenHeaders(),
      path: { saved_search_id: savedSearch.id },
    });
    setPending(null);

    if (!result.response.ok || !result.data) {
      setError(describeGeneratedError(result.error));
      return;
    }

    setError(null);
    setSavedSearches((current) =>
      current.map((row) => (row.id === savedSearch.id ? result.data : row)),
    );
  }

  async function removeSavedSearch(savedSearch: SavedSearchResponse): Promise<void> {
    setPending({ id: savedSearch.id, type: "delete" });
    configureBrowserClient();
    const result = await deleteSavedSearch({
      headers: getAccessTokenHeaders(),
      path: { saved_search_id: savedSearch.id },
    });
    setPending(null);

    if (!result.response.ok) {
      setError(describeGeneratedError(result.error));
      return;
    }

    setError(null);
    setSavedSearches((current) =>
      current.filter((row) => row.id !== savedSearch.id),
    );
  }

  if (loading) {
    return <TableSkeleton />;
  }

  return (
    <div className="space-y-4">
      {error ? (
        <p
          className="rounded-md border border-error/30 bg-error/10 px-3 py-2 text-sm text-error"
          role="alert"
        >
          {error}
        </p>
      ) : null}

      {savedSearches.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-border-strong p-12 text-center shadow-sm">
          <h2 className="font-heading text-xl font-bold text-foreground">
            No saved searches yet
          </h2>
          <p className="mt-2 text-sm text-foreground-muted">
            Save an Explore filter set to rerun it here.
          </p>
          <Link
            className="mt-6 inline-flex min-h-12 items-center justify-center rounded-xl bg-foreground px-6 text-sm font-semibold text-background outline-none transition-colors hover:bg-foreground/90 focus-visible:ring-2 focus-visible:ring-accent"
            href="/explore"
          >
            Open Explore
          </Link>
        </div>
      ) : (
        <div className="space-y-3">
          {savedSearches.map((savedSearch) => {
            const pendingType =
              pending?.id === savedSearch.id ? pending.type : null;
            return (
              <article
                aria-label={savedSearch.name}
                className="group rounded-xl border border-border-default bg-surface-1 p-5 transition-colors hover:bg-surface-2"
                key={savedSearch.id}
              >
                <div className="flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-col gap-3 sm:flex-row">
                      <label className="min-w-0 flex-1">
                        <span className="text-[11px] font-bold uppercase tracking-wider text-foreground-muted transition-colors group-hover:text-accent">
                          Saved search name
                        </span>
                        <input
                          className="mt-2 min-h-12 w-full rounded-xl border border-border-default bg-surface-1 px-4 py-2 text-sm font-medium text-foreground outline-none transition-colors focus-visible:border-accent focus-visible:ring-1 focus-visible:ring-accent"
                          onChange={(event) =>
                            setNames((current) => ({
                              ...current,
                              [savedSearch.id]: event.target.value,
                            }))
                          }
                          value={names[savedSearch.id] ?? savedSearch.name}
                        />
                      </label>
                      <button
                        className="inline-flex min-h-12 items-center justify-center rounded-xl border border-border-strong bg-background px-6 text-sm font-semibold text-foreground outline-none transition-colors hover:bg-surface-1 focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-60 sm:self-end"
                        disabled={pendingType === "rename"}
                        onClick={() => void renameSavedSearch(savedSearch)}
                        type="button"
                      >
                        {pendingType === "rename" ? "Saving..." : "Save name"}
                      </button>
                    </div>
                    <div className="mt-5">
                      <FilterTags filters={savedSearch.filters} />
                    </div>
                  </div>

                  <div className="flex flex-wrap gap-2 pt-1 lg:justify-end">
                    <Link
                      className="inline-flex min-h-12 items-center justify-center rounded-xl bg-foreground px-5 text-sm font-semibold text-background outline-none transition-colors hover:bg-foreground/90 focus-visible:ring-2 focus-visible:ring-accent"
                      href={savedSearchFiltersToHref(savedSearch.filters)}
                    >
                      Open
                    </Link>
                    <button
                      className="inline-flex min-h-12 items-center justify-center gap-2 rounded-xl border border-border-default bg-surface-1 px-4 text-sm font-semibold text-foreground outline-none transition-colors hover:bg-surface-2 focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-60"
                      disabled={pendingType === "toggle"}
                      onClick={() => void toggleAlerts(savedSearch)}
                      type="button"
                    >
                      <BellIcon className="h-4 w-4" aria-hidden="true" />
                      {savedSearch.alert_enabled ? "Disable alerts" : "Enable alerts"}
                    </button>
                    <button
                      className="inline-flex min-h-12 items-center justify-center gap-2 rounded-xl border border-error/50 bg-error/5 px-4 text-sm font-semibold text-error outline-none transition-colors hover:bg-error/10 focus-visible:ring-2 focus-visible:ring-error disabled:cursor-not-allowed disabled:opacity-60"
                      disabled={pendingType === "delete"}
                      onClick={() => void removeSavedSearch(savedSearch)}
                      type="button"
                    >
                      <TrashIcon className="h-4 w-4" aria-hidden="true" />
                      Delete
                    </button>
                  </div>
                </div>
              </article>
            );
          })}
        </div>
      )}
    </div>
  );
}
