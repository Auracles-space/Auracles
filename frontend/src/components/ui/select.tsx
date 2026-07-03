import type { SelectHTMLAttributes } from "react";
import { ChevronDownIcon } from "@radix-ui/react-icons";

export type SelectProps = SelectHTMLAttributes<HTMLSelectElement>;

/**
 * Brand-aligned select primitive using native HTML select element.
 */
export function Select({ className = "", children, ...props }: SelectProps) {
  return (
    <div className="relative">
      <select
        className={[
          "appearance-none flex min-h-12 w-full rounded-xl border border-border-default bg-background pl-4 pr-10 py-2 text-sm text-foreground outline-none transition-colors",
          "focus-visible:ring-2 focus-visible:ring-accent",
          "disabled:cursor-not-allowed disabled:opacity-50",
          className,
        ].join(" ")}
        {...props}
      >
        {children}
      </select>
      <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center pr-3">
        <ChevronDownIcon className="h-5 w-5 text-foreground-muted" />
      </div>
    </div>
  );
}
