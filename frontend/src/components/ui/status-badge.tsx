/**
 * Compact status badge primitive.
 *
 * Uses brand-book semantic colors (success / error) at low opacity for the
 * background plus full opacity for icon and text. Border-radius and tracking
 * follow the design skill §5.5.
 */
import { CheckIcon, Cross2Icon } from "@radix-ui/react-icons";

type StatusBadgeProps = {
  status: "ok" | "unavailable";
};

/**
 * Compact readiness badge for one platform component.
 *
 * @param status - Component readiness state from the health API.
 */
export function StatusBadge({ status }: StatusBadgeProps) {
  const isReady = status === "ok";
  const Icon = isReady ? CheckIcon : Cross2Icon;

  const baseClasses =
    "inline-flex h-7 items-center gap-1.5 rounded-badge border px-2 text-xs font-medium uppercase tracking-[0.05em]";
  const variantClasses = isReady
    ? "border-success/30 bg-success/10 text-success"
    : "border-error/30 bg-error/10 text-error";

  return (
    <span className={`${baseClasses} ${variantClasses}`}>
      <Icon aria-hidden="true" className="h-3.5 w-3.5" />
      {isReady ? "Ready" : "Down"}
    </span>
  );
}
