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
    "border-error bg-transparent text-error hover:bg-error/10 focus-visible:outline-error",
  primary:
    "border-transparent bg-foreground text-background hover:bg-foreground/90 shadow-md focus-visible:outline-foreground active:scale-[0.98]",
  secondary:
    "border-2 border-foreground bg-transparent text-foreground hover:bg-foreground hover:text-background focus-visible:outline-foreground",
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
        "inline-flex min-h-11 items-center justify-center rounded-control border px-4 py-2 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-60",
        "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2",
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
