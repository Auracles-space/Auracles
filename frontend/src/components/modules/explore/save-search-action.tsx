"use client";

/**
 * Explore saved-search action.
 *
 * Lets authenticated Operators persist the current Explore filter state without
 * turning the catalog itself into a client-rendered page, and re-run what they
 * saved. The list lives here rather than behind a nav item of its own: saving
 * happens on Explore, so managing what you saved belongs next to it.
 */
import { BookmarkIcon } from "@radix-ui/react-icons";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import { isNonEmpty } from "@/lib/forms/validators";
import { createSavedSearch, listSavedSearches } from "@/lib/generated/sdk.gen";
import type {
  ExploreSearchFilters,
  SavedSearchResponse,
} from "@/lib/generated/types.gen";
import {
  filtersFromExploreSearchParams,
  savedSearchFiltersToHref,
} from "@/lib/marketplace/saved-search-filters";

export { filtersFromExploreSearchParams };

type ExploreSaveSearchActionProps = {
  filters: ExploreSearchFilters;
};

/**
 * Render a compact form that saves current Explore filters.
 *
 * @param props - Current Explore filters captured from the URL.
 */
export function ExploreSaveSearchAction({ filters }: ExploreSaveSearchActionProps) {
  // The name starts empty so the Operator types their own label; the input
  // placeholder is the only prompt, no auto-generated default.
  const [name, setName] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [status, setStatus] = useState<"error" | "success" | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [saved, setSaved] = useState<SavedSearchResponse[]>([]);
  const canSubmit = isNonEmpty(name);

  /** Load the operator's saved searches; a failure just leaves the list empty. */
  const loadSaved = useCallback(async (): Promise<void> => {
    configureBrowserClient();
    const result = await listSavedSearches({ headers: getAccessTokenHeaders() });
    // Deliberately silent: the list is secondary to the save form above it, and
    // an error banner here would read as a failure of the thing being saved.
    setSaved(result.response.ok ? (result.data?.saved_searches ?? []) : []);
  }, []);

  useEffect(() => {
    void loadSaved();
  }, [loadSaved]);

  async function submitSavedSearch(
    event: React.FormEvent<HTMLFormElement>,
  ): Promise<void> {
    event.preventDefault();
    const trimmedName = name.trim();
    setMessage(null);
    setStatus(null);

    if (!trimmedName) {
      setStatus("error");
      setMessage("Enter a saved search name.");
      return;
    }

    setSubmitting(true);
    configureBrowserClient();
    const result = await createSavedSearch({
      body: {
        alert_enabled: false,
        filters,
        name: trimmedName,
      },
      headers: getAccessTokenHeaders(),
    });
    setSubmitting(false);

    if (!result.response.ok) {
      setStatus("error");
      setMessage(describeGeneratedError(result.error));
      return;
    }

    setStatus("success");
    setMessage(`Saved as ${result.data?.name ?? trimmedName}.`);
    setName("");
    // Show what was just saved in the list below without a page reload.
    await loadSaved();
  }

  return (
    <form
      className="rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm"
      onSubmit={submitSavedSearch}
    >
      <div className="mb-4 flex items-start gap-3">
        <BookmarkIcon
          className="mt-0.5 h-5 w-5 shrink-0 text-accent"
          aria-hidden="true"
        />
        <div>
          <h2 className="font-heading text-sm font-bold text-foreground">
            Save this search
          </h2>
          <p className="mt-1 text-xs leading-relaxed text-foreground-muted">
            Bookmark these filters so you can run them again, and get notified
            when new frameworks match.
          </p>
        </div>
      </div>
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end">
        <label className="min-w-0 flex-1" htmlFor="explore-saved-search-name">
          <span className="text-xs font-semibold uppercase tracking-[0.05em] text-foreground-muted">
            Name this search
          </span>
          <input
            className="mt-2 min-h-12 w-full rounded-xl border border-border-default bg-surface-2 px-4 py-2 text-sm text-foreground outline-none transition-colors placeholder:text-foreground-subtle focus-visible:border-accent focus-visible:ring-1 focus-visible:ring-accent"
            id="explore-saved-search-name"
            onChange={(event) => setName(event.target.value)}
            placeholder="e.g. Healthcare risk playbooks"
            value={name}
          />
        </label>
        <button 
          className="inline-flex min-h-12 items-center justify-center gap-2 rounded-xl bg-foreground px-6 text-sm font-semibold text-background outline-none transition-colors hover:bg-foreground/90 focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-60 sm:shrink-0" 
          disabled={submitting || !canSubmit}
          type="submit"
        >
          <BookmarkIcon className="h-4 w-4" aria-hidden="true" />
          {submitting ? "Saving..." : "Save search"}
        </button>
      </div>
      {message ? (
        <p
          className={[
            "mt-4 rounded-xl border px-4 py-3 text-sm",
            status === "success"
              ? "border-success/30 bg-success/10 text-success"
              : "border-error/30 bg-error/10 text-error",
          ].join(" ")}
          role={status === "success" ? "status" : "alert"}
        >
          {message}
        </p>
      ) : null}
      {saved.length > 0 ? (
        <div className="mt-5 border-t border-border-default pt-5">
          <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
            <h3 className="text-xs font-semibold uppercase tracking-[0.05em] text-foreground-muted">
              Your saved searches
            </h3>
            <Link
              className="text-xs font-semibold text-accent outline-none hover:underline focus-visible:ring-2 focus-visible:ring-accent"
              href="/settings/saved-searches"
            >
              Manage saved searches
            </Link>
          </div>
          <ul className="flex flex-col gap-2">
            {saved.map((savedSearch) => (
              <li key={savedSearch.id}>
                <Link
                  className="flex min-h-12 items-center justify-between gap-3 rounded-xl border border-border-default bg-surface-2 px-4 py-2 text-sm text-foreground outline-none transition-colors hover:bg-surface-1 focus-visible:ring-2 focus-visible:ring-accent"
                  href={savedSearchFiltersToHref(savedSearch.filters)}
                >
                  <span className="min-w-0 truncate font-medium">
                    {savedSearch.name}
                  </span>
                  {savedSearch.alert_enabled ? (
                    <span className="shrink-0 rounded-badge border border-success/30 bg-success/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.05em] text-success">
                      Alerts on
                    </span>
                  ) : null}
                </Link>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </form>
  );
}
