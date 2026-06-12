/**
 * Brand-aligned button primitive.
 *
 * Provides the shared Auracles button styles required by Slice 10. The
 * primitive stays intentionally small so feature forms can compose it without
 * pulling business logic into `components/ui`.
 */
import type { ButtonHTMLAttributes, ReactNode } from "react";

type ButtonVariant = "primary" | "secondary" | "destructive";

export type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  children: ReactNode;
  variant?: ButtonVariant;
};

const variantClasses: Record<ButtonVariant, string> = {
  destructive:
    "border-error/50 bg-error/5 text-error hover:bg-error/10 focus-visible:ring-error",
  primary:
    "border-transparent bg-foreground text-background hover:bg-foreground/90 focus-visible:ring-accent shadow-sm",
  secondary:
    "border-border-default bg-surface-1 text-foreground hover:bg-surface-2 focus-visible:ring-accent",
};

/**
 * Render a minimum-touch-target button using Brand Book control styling.
 *
 * @param props - Native button props plus an Auracles visual variant.
 */
export function Button({
  children,
  className = "",
  variant = "primary",
  type = "button",
  ...props
}: ButtonProps) {
  return (
    <button
      className={[
        "inline-flex min-h-12 items-center justify-center gap-2 rounded-xl border px-6 text-sm font-semibold outline-none transition-colors disabled:cursor-not-allowed disabled:opacity-60",
        "focus-visible:ring-2",
        variantClasses[variant],
        className,
      ].join(" ")}
      type={type}
      {...props}
    >
      {children}
    </button>
  );
}
