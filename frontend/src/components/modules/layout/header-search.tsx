"use client";

/**
 * Global header search.
 *
 * Drives the shared deduped Explore catalog feed: submitting routes to
 * `/explore?q=...` (or `/explore` when cleared) so the same server-rendered
 * search path backs both the public and authenticated header inputs.
 */
import { MagnifyingGlassIcon } from "@radix-ui/react-icons";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

import { Spinner } from "@/components/ui/spinner";

type HeaderSearchProps = {
  /** Visual variant: public marketplace bar vs authenticated app bar. */
  variant?: "public" | "app";
  placeholder?: string;
};

const FIELD_HEIGHT: Record<NonNullable<HeaderSearchProps["variant"]>, string> = {
  public: "h-9",
  app: "h-10",
};

const FIELD_SURFACE: Record<NonNullable<HeaderSearchProps["variant"]>, string> = {
  public: "bg-surface-2",
  app: "bg-surface-1 shadow-sm",
};

/**
 * Render the header search field that submits into the Explore feed.
 *
 * @param props - Visual variant and placeholder copy.
 */
export function HeaderSearch({
  variant = "public",
  placeholder = "Search frameworks, projects...",
}: HeaderSearchProps) {
  const router = useRouter();
  const [query, setQuery] = useState("");
  // startTransition keeps isPending true until the SSR Explore navigation
  // commits, so the field shows a spinner for the whole search round-trip.
  const [isPending, startTransition] = useTransition();

  function handleSubmit(event: React.FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    const trimmed = query.trim();
    // Reset to the full feed when the field is empty so submitting an empty
    // search is never a dead action.
    const href = trimmed
      ? `/explore?${new URLSearchParams({ q: trimmed }).toString()}`
      : "/explore";
    startTransition(() => {
      router.push(href);
    });
  }

  return (
    <form className="relative w-full" onSubmit={handleSubmit} role="search">
      {isPending ? (
        <Spinner
          aria-label="Searching"
          className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-accent"
        />
      ) : (
        <MagnifyingGlassIcon
          aria-hidden
          className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-foreground-muted"
        />
      )}
      <input
        aria-label="Search the marketplace"
        className={`${FIELD_HEIGHT[variant]} ${FIELD_SURFACE[variant]} w-full rounded-xl border border-border-default pl-9 pr-4 text-sm text-foreground placeholder:text-foreground-muted transition-colors focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent`}
        onChange={(event) => setQuery(event.target.value)}
        placeholder={placeholder}
        type="search"
        value={query}
      />
    </form>
  );
}
