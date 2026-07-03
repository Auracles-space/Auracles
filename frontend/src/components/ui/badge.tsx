import type { ReactNode } from "react";

export type BadgeVariant = "success" | "warning" | "error" | "info" | "default";

export type BadgeProps = {
  children: ReactNode;
  variant?: BadgeVariant;
  className?: string;
};

const variantClasses: Record<BadgeVariant, string> = {
  success: "bg-[#16A34A]/10 text-[#16A34A] border-[#16A34A]/30",
  warning: "bg-[#F59E0B]/10 text-[#F59E0B] border-[#F59E0B]/30",
  error: "bg-[#DC2626]/10 text-[#DC2626] border-[#DC2626]/30",
  info: "bg-[#2563EB]/10 text-[#2563EB] border-[#2563EB]/30",
  default: "bg-surface-2 text-foreground-muted border-border-default",
};

/**
 * Brand-aligned compact badge for statuses and tags.
 */
export function Badge({ children, variant = "default", className = "" }: BadgeProps) {
  return (
    <span
      className={[
        "inline-flex h-7 items-center justify-center gap-1.5 rounded-badge border px-3 text-xs font-semibold uppercase tracking-[0.05em]",
        variantClasses[variant],
        className,
      ].join(" ")}
    >
      {children}
    </span>
  );
}
