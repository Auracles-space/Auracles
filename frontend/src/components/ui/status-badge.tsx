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

  return (
    <span
      className={
        isReady
          ? "inline-flex h-7 items-center gap-1.5 rounded border border-[#2A3A2A] bg-[#1A2A1A] px-2 text-xs font-medium uppercase tracking-[0.05em] text-[#86EFAC]"
          : "inline-flex h-7 items-center gap-1.5 rounded border border-[#3A2020] bg-[#2A1010] px-2 text-xs font-medium uppercase tracking-[0.05em] text-[#FCA5A5]"
      }
    >
      <Icon aria-hidden="true" className="h-3.5 w-3.5" />
      {isReady ? "Ready" : "Down"}
    </span>
  );
}
