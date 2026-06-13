"use client";

/**
 * Debounced marketplace search input.
 *
 * The parent decides whether to mutate URL state or submit a request; this
 * component only captures the query and emits stable debounced values.
 */
import { MagnifyingGlassIcon } from "@radix-ui/react-icons";
import { useEffect, useState } from "react";

type SearchInputProps = {
  initialValue?: string;
  onSearch?: (query: string) => void;
};

/**
 * Render a Brand Book-aligned search input with debounce.
 *
 * @param props - Initial query and debounced callback.
 */
export function SearchInput({ initialValue = "", onSearch }: SearchInputProps) {
  const [query, setQuery] = useState(initialValue);

  useEffect(() => {
    if (!onSearch) {
      return;
    }

    const timeout = window.setTimeout(() => {
      onSearch(query.trim());
    }, 300);

    return () => window.clearTimeout(timeout);
  }, [onSearch, query]);

  return (
    <label className="block">
      <span className="mb-2 block text-xs font-semibold uppercase tracking-[0.05em] text-foreground-muted">
        Search frameworks
      </span>
      <span className="flex min-h-12 items-center gap-3 rounded-xl border border-border-default bg-surface-2 px-3 focus-within:border-accent">
        <MagnifyingGlassIcon aria-hidden className="h-4 w-4 text-foreground-muted" />
        <input
          className="min-h-12 w-full bg-transparent text-sm text-foreground outline-none placeholder:text-foreground-subtle"
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Risk, compliance, operating model"
          value={query}
        />
      </span>
    </label>
  );
}
