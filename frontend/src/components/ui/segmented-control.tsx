"use client";

/**
 * Segmented filter control.
 *
 * A row of mutually exclusive options (status filters, view modes) rendered
 * as one bordered group with the active segment filled in ink. Each segment
 * is a 44px touch target and reports `aria-pressed`, so screen readers hear
 * the current filter without a separate live region.
 */

export type SegmentOption<T extends string> = {
  value: T;
  label: string;
  /** Optional count shown after the label when greater than 0. */
  count?: number;
};

type SegmentedControlProps<T extends string> = {
  options: SegmentOption<T>[];
  value: T;
  onChange: (value: T) => void;
  /** Accessible name for the group (e.g. "Filter applications by status"). */
  label: string;
  className?: string;
};

/**
 * Render a segmented single-select control.
 *
 * @param props - Options, current value, change handler, accessible label.
 */
export function SegmentedControl<T extends string>({
  options,
  value,
  onChange,
  label,
  className = "",
}: SegmentedControlProps<T>) {
  return (
    <nav
      aria-label={label}
      className={`flex flex-wrap gap-1 rounded-2xl border border-border-default bg-surface-2 p-1.5 ${className}`}
    >
      {options.map((option) => {
        const isActive = option.value === value;
        return (
          <button
            aria-pressed={isActive}
            className={[
              "inline-flex min-h-11 flex-1 items-center justify-center gap-2 whitespace-nowrap rounded-xl px-4 text-sm font-semibold outline-none transition-colors focus-visible:ring-2 focus-visible:ring-accent",
              isActive
                ? "bg-foreground text-background"
                : "text-foreground-muted hover:bg-surface-1 hover:text-foreground",
            ].join(" ")}
            key={option.value}
            onClick={() => onChange(option.value)}
            type="button"
          >
            {option.label}
            {option.count !== undefined && option.count > 0 ? (
              <span
                className={[
                  "inline-flex min-w-5 items-center justify-center rounded-badge px-1.5 text-xs font-semibold tabular-nums",
                  isActive ? "bg-background/20 text-background" : "bg-surface-3 text-foreground-muted",
                ].join(" ")}
              >
                {option.count}
              </span>
            ) : null}
          </button>
        );
      })}
    </nav>
  );
}
