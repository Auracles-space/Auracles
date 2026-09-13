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
  // One line per blocked capability, saying why: a suspended or revoked
  // capability is not the same as one nobody has activated yet.
  const hints = CAPABILITY_META.filter(({ key }) => orgCapabilities[key] !== "active").map(
    ({ key, label }) => {
      const status = orgCapabilities[key];
      if (status === "suspended") {
        return `${label} is suspended for the organization.`;
      }
      if (status === "revoked") {
        return `${label} was revoked for the organization.`;
      }
      return `Activate ${label} for the organization first.`;
    },
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
      {hints.length > 0 ? (
        <ul className="grid gap-0.5 text-xs text-foreground-muted">
          {hints.map((hint) => (
            <li key={hint}>{hint}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
