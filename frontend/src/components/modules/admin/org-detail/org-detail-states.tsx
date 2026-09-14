"use client";

/**
 * Shared building blocks for the admin organization detail tabs: the loading
 * skeleton, the described error with Retry, bento sections, labelled facts
 * and the phone-card / md-row list item.
 *
 * Maps to: organizations end-to-end design, Slice D (admin org detail).
 */
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";

/** Placeholder rows shown while a tab's endpoint loads. */
export function PanelSkeleton() {
  return (
    <div aria-busy="true" aria-label="Loading" className="grid gap-3" role="status">
      <Skeleton className="h-6 w-40" />
      <Skeleton className="h-20 w-full rounded-xl" />
      <Skeleton className="h-20 w-full rounded-xl" />
    </div>
  );
}

/**
 * A described load failure with a Retry action.
 *
 * @param message - Human-readable reason from the API.
 * @param onRetry - Refetch the failed resource.
 */
export function PanelError({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="grid gap-3 rounded-xl border border-error/30 bg-error/10 p-4" role="alert">
      <p className="text-sm text-error">{message}</p>
      <Button className="w-full sm:w-fit" onClick={onRetry} variant="secondary">
        Retry
      </Button>
    </div>
  );
}

/**
 * A titled bento section inside a tab.
 *
 * @param title - Section heading.
 * @param aside - Optional trailing content next to the heading.
 * @param children - Section body.
 */
export function Section({ title, aside, children }: { title: string; aside?: ReactNode; children: ReactNode }) {
  return (
    <section className="grid gap-3 rounded-2xl border border-border-default bg-surface-1 p-4 shadow-sm md:p-6">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="font-heading text-lg font-bold text-foreground">{title}</h2>
        {aside ? <div className="text-sm text-foreground-muted">{aside}</div> : null}
      </div>
      {children}
    </section>
  );
}

/**
 * One labelled fact (term and value).
 *
 * @param label - Short uppercase label.
 * @param children - Value to show; falls back to "Not provided".
 */
export function Fact({ label, children }: { label: string; children?: ReactNode }) {
  return (
    <div className="grid gap-1 rounded-xl border border-border-default bg-surface-2 p-3">
      <dt className="text-xs font-semibold uppercase tracking-[0.05em] text-foreground-muted">{label}</dt>
      <dd className="break-words text-sm text-foreground">{children || "Not provided"}</dd>
    </div>
  );
}

/**
 * A list item that stacks as a card on phones and aligns as a row from md up.
 *
 * @param columns - Tailwind md grid-template class for the row layout.
 * @param children - Cells in display order.
 */
export function ListRow({ columns, children }: { columns: string; children: ReactNode }) {
  return (
    <li
      className={`grid gap-2 rounded-xl border border-border-default bg-surface-2 p-4 md:items-center md:gap-4 md:py-3 ${columns}`}
    >
      {children}
    </li>
  );
}

/**
 * Muted copy for an empty list.
 *
 * @param children - What is absent.
 */
export function EmptyNote({ children }: { children: ReactNode }) {
  return <p className="text-sm text-foreground-muted">{children}</p>;
}
