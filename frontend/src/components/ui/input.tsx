import type { InputHTMLAttributes } from "react";

export type InputProps = InputHTMLAttributes<HTMLInputElement>;

/**
 * Brand-aligned text input primitive.
 */
export function Input({ className = "", ...props }: InputProps) {
  return (
    <input
      className={[
        "flex min-h-12 w-full rounded-xl border border-border-default bg-background px-4 py-2 text-sm text-foreground placeholder:text-foreground-muted outline-none transition-colors",
        "focus-visible:ring-2 focus-visible:ring-accent",
        "disabled:cursor-not-allowed disabled:opacity-50",
        className,
      ].join(" ")}
      {...props}
    />
  );
}
