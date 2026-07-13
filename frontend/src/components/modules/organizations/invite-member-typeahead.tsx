"use client";

/**
 * Invite member typeahead for organization admins.
 *
 * Debounces the admin's input and searches existing users with the masked
 * member-search endpoint. Selecting a suggestion emits the picked user id;
 * typing continues to support the manual outsider-email path.
 */
import { useEffect, useId, useMemo, useState } from "react";

import { Input } from "@/components/ui/input";
import {
  configureBrowserClient,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import { searchOrgMembers } from "@/lib/generated/sdk.gen";
import type { MemberSearchResult } from "@/lib/generated/types.gen";

type InviteMemberTypeaheadProps = {
  orgId: string;
  disabled?: boolean;
  value: string;
  onSelect: (userId: string) => void;
  onEmailChange: (value: string) => void;
};

function initialsFor(name: string): string {
  const words = name.trim().split(/\s+/).filter(Boolean);
  return words.slice(0, 2).map((word) => word[0]?.toUpperCase() ?? "").join("");
}

/**
 * Render the invite input with masked-member suggestions under it.
 *
 * @param props - Controlled value plus callbacks for manual typing or selection.
 */
export function InviteMemberTypeahead({
  orgId,
  disabled = false,
  value,
  onSelect,
  onEmailChange,
}: InviteMemberTypeaheadProps) {
  const listboxId = useId();
  const [query, setQuery] = useState(value);
  const [selectedLabel, setSelectedLabel] = useState<string | null>(null);
  const [results, setResults] = useState<MemberSearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);

  useEffect(() => {
    if (value === "") {
      setQuery("");
      setSelectedLabel(null);
      return;
    }
    if (selectedLabel === null) {
      setQuery(value);
    }
  }, [selectedLabel, value]);

  const displayValue = useMemo(
    () => selectedLabel ?? query,
    [query, selectedLabel],
  );

  useEffect(() => {
    if (disabled || selectedLabel !== null) {
      setLoading(false);
      setOpen(false);
      return;
    }

    const trimmed = query.trim();
    if (trimmed.length < 3) {
      setResults([]);
      setError(null);
      setLoading(false);
      setOpen(false);
      setActiveIndex(-1);
      return;
    }

    let cancelled = false;
    const timer = window.setTimeout(async () => {
      setLoading(true);
      setError(null);
      configureBrowserClient();
      const result = await searchOrgMembers({
        path: { org_id: orgId },
        query: { q: trimmed },
        headers: getAccessTokenHeaders(),
      });

      if (cancelled) {
        return;
      }

      setLoading(false);
      if (!result.response.ok || !result.data) {
        setResults([]);
        setOpen(false);
        setActiveIndex(-1);
        setError("We could not search members right now.");
        return;
      }

      setResults(result.data.results);
      setOpen(true);
      setActiveIndex(result.data.results.length > 0 ? 0 : -1);
      setError(null);
    }, 250);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [disabled, orgId, query, selectedLabel]);

  function handleChange(nextValue: string): void {
    setSelectedLabel(null);
    setQuery(nextValue);
    setOpen(nextValue.trim().length >= 3);
    setActiveIndex(-1);
    onEmailChange(nextValue);
  }

  function handleSelect(result: MemberSearchResult): void {
    setSelectedLabel(result.display_name);
    setResults([]);
    setOpen(false);
    setActiveIndex(-1);
    setError(null);
    onEmailChange(result.display_name);
    onSelect(result.user_id);
  }

  function handleKeyDown(event: React.KeyboardEvent<HTMLInputElement>): void {
    if (!open || results.length === 0) {
      return;
    }

    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActiveIndex((current) => (current + 1) % results.length);
      return;
    }

    if (event.key === "ArrowUp") {
      event.preventDefault();
      setActiveIndex((current) =>
        current <= 0 ? results.length - 1 : current - 1,
      );
      return;
    }

    if (event.key === "Enter" && activeIndex >= 0) {
      event.preventDefault();
      handleSelect(results[activeIndex]);
      return;
    }

    if (event.key === "Escape") {
      setOpen(false);
      setActiveIndex(-1);
    }
  }

  return (
    <div className="relative">
      <label
        className="mb-1 block text-sm font-semibold text-foreground"
        htmlFor="invite-member-typeahead"
      >
        Invite by email
      </label>
      <Input
        aria-autocomplete="list"
        aria-controls={listboxId}
        aria-expanded={open}
        autoComplete="off"
        disabled={disabled}
        id="invite-member-typeahead"
        onChange={(event) => handleChange(event.target.value)}
        onFocus={() => {
          if (results.length > 0) {
            setOpen(true);
          }
        }}
        onKeyDown={handleKeyDown}
        placeholder="Type a colleague's name or email"
        role="combobox"
        value={displayValue}
      />
      {loading ? (
        <p className="mt-2 text-sm text-foreground-muted">Searching members...</p>
      ) : null}
      {error ? <p className="mt-2 text-sm text-error">{error}</p> : null}
      {open ? (
        <div
          className="absolute z-20 mt-2 w-full rounded-xl border border-border-default bg-surface-1 p-2 shadow-sm"
          role="listbox"
          id={listboxId}
        >
          {results.length === 0 ? (
            <p className="rounded-xl bg-surface-2 px-4 py-3 text-sm text-foreground-muted">
              No matching members.
            </p>
          ) : (
            <div className="grid gap-2">
              {results.map((result, index) => {
                const active = index === activeIndex;
                return (
                  <button
                    className={[
                      "flex min-h-12 w-full items-center gap-3 rounded-xl border px-3 py-3 text-left transition-colors",
                      active
                        ? "border-accent/40 bg-surface-2"
                        : "border-border-default bg-background hover:bg-surface-2",
                    ].join(" ")}
                    key={result.user_id}
                    onClick={() => handleSelect(result)}
                    type="button"
                  >
                    {result.avatar_url ? (
                      <img
                        alt=""
                        className="h-10 w-10 rounded-xl border border-border-default object-cover"
                        src={result.avatar_url}
                      />
                    ) : (
                      <div className="flex h-10 w-10 items-center justify-center rounded-xl border border-border-default bg-surface-2 text-sm font-semibold text-foreground">
                        {initialsFor(result.display_name)}
                      </div>
                    )}
                    <div className="min-w-0">
                      <p className="truncate text-sm font-semibold text-foreground">
                        {result.display_name}
                      </p>
                      <p className="truncate text-sm text-foreground-muted">
                        {result.masked_email}
                      </p>
                    </div>
                  </button>
                );
              })}
            </div>
          )}
        </div>
      ) : null}
    </div>
  );
}
