"use client";

/**
 * Capability wind-down panel (owner-only, step-up gated on the API).
 *
 * Closing an organization is refused while any capability is active, and every
 * capability status change used to be admin-only — so an owner was told to
 * wind down something they had no control for, and account deletion was
 * blocked behind the close. This is that control.
 *
 * Standing down is not a revocation: the capability becomes `withdrawn`, and
 * contributor and operator come back through their existing self-activate
 * while an attestor org re-applies. An attestor's open offers and undelivered
 * reviews are released the same way a revocation releases them, so nobody who
 * paid is left waiting on an organization that has gone.
 *
 * Maps to: docs/superpowers/specs/2026-09-14-organizations-end-to-end-design.md
 * §Decisions 4.
 */
import { useState } from "react";

import {
  withdrawAttestorCapabilityV1OrgsOrgIdAttestorCapabilityWithdrawPost as withdrawAttestor,
  withdrawContributorCapabilityV1OrgsOrgIdContributorCapabilityWithdrawPost as withdrawContributor,
  withdrawOperatorCapabilityV1OrgsOrgIdOperatorCapabilityWithdrawPost as withdrawOperator,
} from "@/lib/generated/sdk.gen";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import { Button } from "@/components/ui/button";
import { capabilityLabel } from "./capability-labels";
import { useOrganization } from "./organization-context";

type WithdrawCall = (options: {
  path: { org_id: string };
  headers: Record<string, string>;
}) => Promise<{ response: { ok: boolean }; error?: unknown }>;

/** The stand-down call for each capability, and what it costs the org. */
const WITHDRAW: Record<string, { call: WithdrawCall; consequence: string }> = {
  contributor: {
    call: withdrawContributor as WithdrawCall,
    consequence:
      "Your frameworks leave the marketplace. Licences already sold are unaffected, and re-activating puts them back.",
  },
  operator: {
    call: withdrawOperator as WithdrawCall,
    consequence:
      "Your organization stops buying. Frameworks you have already licensed stay in your library.",
  },
  attestor: {
    call: withdrawAttestor as WithdrawCall,
    consequence:
      "Open offers pass to other attestors and reviews you have not delivered go to an admin to reassign. You would need to apply again to attest.",
  },
};

/**
 * Render a stand-down control for each active capability.
 *
 * @param onChange - Refetch callback fired after a capability stands down.
 */
export function OrganizationCapabilityWindDown({
  onChange,
}: {
  onChange: () => void;
}) {
  const { orgId, capabilities, role } = useOrganization();
  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const active = Object.entries(capabilities ?? {}).filter(
    ([capability, status]) => status === "active" && capability in WITHDRAW,
  );

  // Leaving the marketplace is the owner's call; an org admin can activate a
  // capability but not stand one down.
  if (role !== "owner") {
    return null;
  }

  async function standDown(capability: string): Promise<void> {
    setPending(capability);
    setError(null);
    try {
      configureBrowserClient();
      const result = await WITHDRAW[capability].call({
        path: { org_id: orgId },
        headers: getAccessTokenHeaders(),
      });
      if (!result.response.ok) {
        setError(describeGeneratedError(result.error));
        return;
      }
      onChange();
    } catch (caught) {
      setError(describeGeneratedError(caught));
    } finally {
      setPending(null);
    }
  }

  return (
    <section className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm md:p-8">
      <h2 className="font-heading text-xl font-bold text-foreground">
        Wind down capabilities
      </h2>
      <p className="mt-2 max-w-2xl text-sm leading-6 text-foreground-muted">
        An organization can only be closed once it has stopped trading. Standing
        a capability down is reversible — this is not a suspension, and no
        administrator is involved.
      </p>

      {error ? (
        <p
          className="mt-4 rounded-xl border border-error/30 bg-error/10 px-4 py-3 text-sm text-error"
          role="alert"
        >
          {error}
        </p>
      ) : null}

      {active.length === 0 ? (
        <p className="mt-5 rounded-xl border border-success/30 bg-success/10 px-4 py-3 text-sm text-success">
          No active capabilities. This organization can be closed below.
        </p>
      ) : (
        <ul className="mt-5 flex flex-col gap-3">
          {active.map(([capability]) => (
            <li
              className="flex flex-col gap-3 rounded-xl border border-border-default bg-surface-2 p-4 sm:flex-row sm:items-center sm:justify-between"
              key={capability}
            >
              <div className="min-w-0">
                <p className="text-sm font-semibold text-foreground">
                  {capabilityLabel(capability)}
                </p>
                <p className="mt-1 text-sm leading-6 text-foreground-muted">
                  {WITHDRAW[capability].consequence}
                </p>
              </div>
              <Button
                disabled={pending !== null}
                loading={pending === capability}
                onClick={() => void standDown(capability)}
                type="button"
                variant="secondary"
              >
                Stand down {capabilityLabel(capability)}
              </Button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
