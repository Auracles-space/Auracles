/**
 * Per-team capability controls.
 *
 * Renders the Contributor, Operator, and Attestor controls for one team using
 * the org capability map as the eligibility gate.
 */
import type { OrgTeamResponse } from "@/lib/generated/types.gen";

const CAPABILITY_META = [
  { key: "contributor", label: "Contributor" },
  { key: "operator", label: "Operator" },
  { key: "attestor", label: "Attestor" },
] as const;

export type TeamCapabilityKey = (typeof CAPABILITY_META)[number]["key"];

type TeamCapabilityTogglesProps = {
  team: OrgTeamResponse;
  orgCapabilities: Record<string, string>;
  isBusy?: boolean;
  onToggle: (
    capability: TeamCapabilityKey,
    enabled: boolean,
  ) => void;
};

/**
 * Render one team's capability assignment controls.
 *
 * @param props - Team row data and the org-level capability status map.
 */
export function TeamCapabilityToggles({
  team,
  orgCapabilities,
  isBusy = false,
  onToggle,
}: TeamCapabilityTogglesProps) {
  const showHint = CAPABILITY_META.some(
    ({ key }) => orgCapabilities[key] !== "active",
  );

  return (
    <div className="mt-3 flex flex-col gap-2">
      <div className="flex flex-wrap gap-2">
        {CAPABILITY_META.map(({ key, label }) => {
          const enabled = team.capabilities?.includes(key) ?? false;
          const inactive = orgCapabilities[key] !== "active";
          const action = enabled ? "Disable" : "Enable";

          return (
            <button
              key={key}
              aria-label={`${action} ${label} on ${team.name}`}
              className={[
                "min-h-11 rounded-xl border px-3 py-2 text-sm font-semibold transition-colors",
                enabled
                  ? "border-accent/40 bg-accent/10 text-accent"
                  : "border-border-default bg-surface-1 text-foreground",
                inactive
                  ? "cursor-not-allowed opacity-60"
                  : "hover:border-accent/40 hover:bg-surface-2",
              ].join(" ")}
              disabled={inactive || isBusy}
              onClick={() => onToggle(key, enabled)}
              type="button"
            >
              {label}
            </button>
          );
        })}
      </div>
      {showHint ? (
        <p className="text-xs text-foreground-muted">
          Activate this capability for the organization first.
        </p>
      ) : null}
    </div>
  );
}
