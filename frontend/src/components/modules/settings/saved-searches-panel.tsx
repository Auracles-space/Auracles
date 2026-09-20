"use client";

/**
 * Operator saved-search settings panel.
 *
 * Lists owned Explore saved searches and provides client-side controls for
 * rename, alert toggle, deletion, and opening the current filter snapshot.
 *
 * A saved-search alert links here with `?highlight=<id>`, since there is no
 * per-search page: the named row is outlined and scrolled to so the recipient
 * sees which search matched rather than hunting through their list.
 */
import { BellIcon, TrashIcon } from "@radix-ui/react-icons";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";

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
      <span className="rounded-md border border-border-default bg-surface-3 px-2.5 py-1 text-xs font-medium text-foreground-muted">
        All marketplace items
      </span>
    );
  }

  return (
    <div className="flex flex-wrap gap-2">
      {entries.slice(0, 6).map(([key, value]) => (
        <span
          className="rounded-md border border-border-default bg-surface-3 px-2.5 py-1 text-xs font-medium text-foreground-muted"
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
  const highlightedId = useSearchParams().get("highlight");
  const highlightedRef = useRef<HTMLElement | null>(null);

  // Scroll once the row exists. A search that was deleted, or a link opened by
  // someone who does not own it, simply leaves nothing to scroll to. The
  // feature-check is not belt-and-braces: jsdom has no scrollIntoView, and an
  // unguarded call throws out of the effect and unmounts the whole panel.
  useEffect(() => {
    const element = highlightedRef.current;
    if (typeof element?.scrollIntoView === "function") {
      element.scrollIntoView({ block: "center" });
    }
  }, [highlightedId, savedSearches]);

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
            const currentName = names[savedSearch.id] ?? savedSearch.name;
            const isNameEdited =
              names[savedSearch.id] !== undefined &&
              currentName.trim() !== "" &&
              currentName.trim() !== savedSearch.name.trim();

            const isHighlighted = savedSearch.id === highlightedId;

            return (
              <article
                aria-current={isHighlighted ? "true" : undefined}
                aria-label={savedSearch.name}
                className={`group rounded-2xl border bg-surface-1 p-6 shadow-bento transition-all duration-300 hover:shadow-card ${
                  isHighlighted
                    ? "border-accent ring-1 ring-accent"
                    : "border-border-default hover:border-accent/30"
                }`}
                key={savedSearch.id}
                ref={isHighlighted ? highlightedRef : undefined}
              >
                <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
                  {/* Left Column - Input and Filter summary */}
                  <div className="lg:col-span-8 flex flex-col gap-4">
                    <div className="flex flex-col sm:flex-row items-end gap-3">
                      <label className="min-w-0 flex-1 w-full">
                        <span className="text-[10px] font-bold uppercase tracking-wider text-accent mb-2 block">
                          Saved search name
                        </span>
                        <input
                          className="min-h-12 w-full rounded-xl border border-border-default bg-surface-2 px-4 py-2 text-sm font-medium text-foreground outline-none transition-all focus-visible:border-accent focus-visible:bg-background focus-visible:ring-1 focus-visible:ring-accent"
                          onChange={(event) =>
                            setNames((current) => ({
                              ...current,
                              [savedSearch.id]: event.target.value,
                            }))
                          }
                          value={currentName}
                        />
                      </label>
                      <button
                        className="inline-flex min-h-12 w-full sm:w-auto items-center justify-center gap-1.5 rounded-xl border border-border-default bg-background px-5 text-sm font-semibold text-foreground outline-none transition-all hover:bg-surface-2 hover:border-border-strong focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-60 shrink-0"
                        disabled={pendingType === "rename" || !isNameEdited}
                        onClick={() => void renameSavedSearch(savedSearch)}
                        type="button"
                      >
                        <svg className="h-4 w-4 text-foreground-muted" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                          <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                        </svg>
                        {pendingType === "rename" ? "Saving..." : "Save name"}
                      </button>
                    </div>

                    {/* Nested Filter Summary container (Surface Level 2) */}
                    <div className="rounded-xl border border-border-default/40 bg-surface-2/60 p-4 mt-2">
                      <span className="text-[10px] font-bold uppercase tracking-wider text-foreground-subtle mb-2.5 block">
                        Search Parameters
                      </span>
                      <FilterTags filters={savedSearch.filters} />
                    </div>
                  </div>

                  {/* Right Column - Actions Panel */}
                  <div className="lg:col-span-4 flex flex-col sm:flex-row lg:flex-col items-stretch justify-end lg:justify-start gap-2.5 border-t border-border-default/50 lg:border-t-0 pt-4 lg:pt-0">
                    <span className="text-[10px] font-bold uppercase tracking-wider text-foreground-subtle mb-1 hidden lg:block text-right">
                      Actions
                    </span>
                    <Link
                      className="inline-flex min-h-12 items-center justify-center gap-2 rounded-xl bg-foreground px-5 text-sm font-semibold text-background outline-none transition-colors hover:bg-foreground/90 focus-visible:ring-2 focus-visible:ring-accent text-center w-full"
                      href={savedSearchFiltersToHref(savedSearch.filters)}
                    >
                      <svg className="h-4 w-4 text-background" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
                      </svg>
                      Open
                    </Link>
                    <button
                      className="inline-flex min-h-12 items-center justify-center gap-2 rounded-xl border border-border-default bg-surface-1 px-4 text-sm font-semibold text-foreground outline-none transition-colors hover:bg-surface-2 focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-60 w-full"
                      disabled={pendingType === "toggle"}
                      onClick={() => void toggleAlerts(savedSearch)}
                      type="button"
                    >
                      <BellIcon className="h-4 w-4" aria-hidden="true" />
                      {savedSearch.alert_enabled ? "Disable alerts" : "Enable alerts"}
                    </button>
                    <button
                      className="inline-flex min-h-12 items-center justify-center gap-2 rounded-xl border border-error/50 bg-error/5 px-4 text-sm font-semibold text-error outline-none transition-colors hover:bg-error/10 focus-visible:ring-2 focus-visible:ring-error disabled:cursor-not-allowed disabled:opacity-60 w-full"
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
