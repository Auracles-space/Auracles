"use client";

/**
 * Accessible underline Tabs primitive.
 *
 * Renders a WAI-ARIA tablist: roving tabindex, arrow/Home/End keyboard
 * navigation, and `aria-selected` state. Panels are owned by the caller and
 * wired with `tabPanelProps(id)` / `tabId(id)`. Purely presentational — the
 * caller holds the active id and decides what each panel renders.
 */
import type { KeyboardEvent } from "react";

export type TabItem = {
  /** Stable identifier used for selection, ids, and deep-linking. */
  id: string;
  /** Visible, human-readable tab label. */
  label: string;
  /**
   * Optional item count. A badge renders only when this is greater than 0,
   * shown compact (e.g. "1.2K") with the exact value available on hover.
   */
  count?: number;
  /**
   * Optional binary attention marker. Renders a small dot (no number) when
   * true and `count` is not greater than 0 — for yes/no states like an
   * unsigned NDA. Falls behind `count` when both are set.
   */
  dot?: boolean;
  /** Accessible label for the dot marker (e.g. "Action required"). */
  dotLabel?: string;
};

/** Format a tab count compactly for the badge (e.g. 1234 → "1.2K"). */
function formatTabCount(count: number): string {
  return new Intl.NumberFormat("en-US", {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(count);
}

type TabsProps = {
  /** Tabs to render, in display order. */
  tabs: TabItem[];
  /** Currently selected tab id. */
  activeId: string;
  /** Called with the id of the tab the user selected. */
  onChange: (id: string) => void;
  /** Accessible name for the tablist (e.g. "Projects"). */
  label: string;
};

/** Build the DOM id for a tab control. */
export function tabId(id: string): string {
  return `tab-${id}`;
}

/** Build the DOM id for a tab's panel. */
export function tabPanelId(id: string): string {
  return `tabpanel-${id}`;
}

/**
 * Render an accessible underline tablist.
 *
 * @param tabs - Tabs to render, in order.
 * @param activeId - The selected tab id.
 * @param onChange - Selection callback.
 * @param label - Accessible name for the tablist.
 */
export function Tabs({ tabs, activeId, onChange, label }: TabsProps) {
  function moveSelection(event: KeyboardEvent<HTMLButtonElement>): void {
    const currentIndex = tabs.findIndex((tab) => tab.id === activeId);
    if (currentIndex === -1) {
      return;
    }
    let nextIndex: number | null = null;
    if (event.key === "ArrowRight") {
      nextIndex = (currentIndex + 1) % tabs.length;
    } else if (event.key === "ArrowLeft") {
      nextIndex = (currentIndex - 1 + tabs.length) % tabs.length;
    } else if (event.key === "Home") {
      nextIndex = 0;
    } else if (event.key === "End") {
      nextIndex = tabs.length - 1;
    }
    if (nextIndex !== null) {
      event.preventDefault();
      onChange(tabs[nextIndex].id);
    }
  }

  return (
    <div
      aria-label={label}
      className="flex gap-1 overflow-x-auto border-b border-border-default"
      role="tablist"
    >
      {tabs.map((tab) => {
        const selected = tab.id === activeId;
        return (
          <button
            aria-controls={tabPanelId(tab.id)}
            aria-selected={selected}
            className={[
              "-mb-px inline-flex min-h-11 shrink-0 items-center whitespace-nowrap border-b-2 px-4 text-sm font-semibold outline-none transition-colors",
              "focus-visible:ring-2 focus-visible:ring-accent",
              selected
                ? "border-accent text-accent"
                : "border-transparent text-foreground-muted hover:text-foreground",
            ].join(" ")}
            id={tabId(tab.id)}
            key={tab.id}
            onClick={() => onChange(tab.id)}
            onKeyDown={moveSelection}
            role="tab"
            tabIndex={selected ? 0 : -1}
            type="button"
          >
            {tab.label}
            {tab.count !== undefined && tab.count > 0 ? (
              <span
                className={[
                  "ml-2 inline-flex min-w-[1.25rem] items-center justify-center rounded-full px-1.5 py-0.5 text-xs font-semibold tabular-nums",
                  selected
                    ? "bg-accent/10 text-accent"
                    : "bg-surface-3 text-foreground-muted",
                ].join(" ")}
                title={tab.count.toLocaleString("en-US")}
              >
                {formatTabCount(tab.count)}
              </span>
            ) : tab.dot ? (
              <span
                aria-label={tab.dotLabel ?? "Action required"}
                className="ml-2 h-2 w-2 rounded-full bg-accent ring-4 ring-accent/15"
                role="img"
              />
            ) : null}
          </button>
        );
      })}
    </div>
  );
}
