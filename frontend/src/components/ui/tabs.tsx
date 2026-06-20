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
};

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
          </button>
        );
      })}
    </div>
  );
}
