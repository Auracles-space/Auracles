import type { TextareaHTMLAttributes } from "react";

export type TextareaProps = TextareaHTMLAttributes<HTMLTextAreaElement>;

/**
 * Brand-aligned textarea primitive.
 */
export function Textarea({ className = "", ...props }: TextareaProps) {
  return (
    <textarea
      className={[
        "flex min-h-[100px] w-full rounded-xl border border-border-default bg-background px-4 py-3 text-sm text-foreground placeholder:text-foreground-muted outline-none transition-colors",
        "focus-visible:ring-2 focus-visible:ring-accent",
        "disabled:cursor-not-allowed disabled:opacity-50",
        className,
      ].join(" ")}
      {...props}
    />
  );
}
