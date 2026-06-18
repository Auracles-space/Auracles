"use client";

/**
 * Explore sort menu.
 *
 * Renders catalog ordering as links so changing sort preserves the active
 * search + filter state. A small amount of client state closes the menu on an
 * outside click or Escape, which the native <details> element does not do.
 */
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import type { ExploreSort } from "@/lib/generated/types.gen";

import { buildExploreFilterHref } from "./filter-sidebar";

type SortMenuProps = {
  active: Record<string, string | undefined>;
  current: ExploreSort;
};

const SORT_OPTIONS: { label: string; value: ExploreSort }[] = [
  { label: "Newest", value: "newest" },
  { label: "Top rated", value: "top-rated" },
  { label: "Most purchased", value: "most-purchased" },
  { label: "Price: low to high", value: "price_asc" },
  { label: "Price: high to low", value: "price_desc" },
];

/**
 * Render the active sort label for the trigger button.
 *
 * @param current - Active sort value.
 * @returns Human-readable sort label.
 */
function sortLabel(current: ExploreSort): string {
  return SORT_OPTIONS.find((option) => option.value === current)?.label ?? "Newest";
}

/**
 * Render a sort dropdown of links that preserves the active query.
 *
 * @param props - Active query params and the current sort value.
 */
export function SortMenu({ active, current }: SortMenuProps) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) {
      return;
    }
    function handlePointerDown(event: MouseEvent) {
      if (!containerRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [open]);

  return (
    <div className="relative" ref={containerRef}>
      <button
        aria-expanded={open}
        aria-haspopup="menu"
        className="flex min-h-11 items-center gap-2 rounded-xl border border-border-default px-3 py-1.5 text-sm font-medium text-foreground-muted outline-none transition-colors hover:bg-surface-2 focus-visible:ring-2 focus-visible:ring-accent"
        onClick={() => setOpen((value) => !value)}
        type="button"
      >
        <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 4a1 1 0 011-1h16a1 1 0 011 1v2.586a1 1 0 01-.293.707l-6.414 6.414a1 1 0 00-.293.707V17l-4 4v-6.586a1 1 0 00-.293-.707L3.293 7.293A1 1 0 013 6.586V4z" />
        </svg>
        Sort: {sortLabel(current)}
        <svg
          className={[
            "ml-1 h-3 w-3 transition-transform duration-200",
            open ? "rotate-180" : "",
          ].join(" ")}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>
      {open ? (
        <div
          className="absolute right-0 z-20 mt-2 w-56 overflow-hidden rounded-xl border border-border-default bg-surface-1 p-1.5 shadow-card"
          role="menu"
        >
          {SORT_OPTIONS.map((option) => {
            const selected = option.value === current;
            return (
              <Link
                className={[
                  "block rounded-lg px-3 py-2 text-sm transition-colors",
                  selected
                    ? "bg-accent/10 font-medium text-accent"
                    : "text-foreground hover:bg-surface-2",
                ].join(" ")}
                href={buildExploreFilterHref(active, "sort", option.value)}
                key={option.value}
                onClick={() => setOpen(false)}
                role="menuitem"
              >
                {option.label}
              </Link>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}
