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
    "inline-flex h-7 items-center gap-1.5 rounded border px-2 text-xs font-medium uppercase tracking-[0.05em]";
  const variantClasses = isReady
    ? "border-status-success-border bg-status-success-bg text-status-success-text"
    : "border-status-error-border bg-status-error-bg text-status-error-text";

  return (
    <span className={`${baseClasses} ${variantClasses}`}>
      <Icon aria-hidden="true" className="h-3.5 w-3.5" />
      {isReady ? "Ready" : "Down"}
    </span>
  );
}
