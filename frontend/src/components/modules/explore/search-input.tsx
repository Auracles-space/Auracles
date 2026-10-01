"use client";

/**
 * Debounced marketplace search input.
 *
 * The parent decides whether to mutate URL state or submit a request; this
 * component only captures the query and emits stable debounced values.
 */
import { MagnifyingGlassIcon } from "@radix-ui/react-icons";
import { useEffect, useRef, useState } from "react";

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

  // Held in a ref, not read from the closure. `SearchPanel` builds `onSearch`
  // with `useCallback(..., [router, searchParams])`, so every navigation gives
  // it a new identity — and with that identity in the dependency list this
  // effect re-armed its timer, fired again, navigated again, for as long as the
  // tab stayed open. Each navigation re-rendered the server component and
  // refetched the catalog: ~6 requests a second of one unchanging query.
  const onSearchRef = useRef(onSearch);
  useEffect(() => {
    onSearchRef.current = onSearch;
  }, [onSearch]);

  // What the parent already knows about, so an unchanged query emits nothing.
  // Seeded from `initialValue` because arriving at `/explore?q=risk` already
  // has its results; re-emitting that query navigates for nothing.
  const lastEmitted = useRef(initialValue.trim());

  useEffect(() => {
    const next = query.trim();
    if (next === lastEmitted.current) {
      return;
    }

    const timeout = window.setTimeout(() => {
      lastEmitted.current = next;
      onSearchRef.current?.(next);
    }, 300);

    return () => window.clearTimeout(timeout);
  }, [query]);

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
