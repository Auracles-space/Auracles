"use client";

/**
 * Account roles settings panel.
 *
 * Roles were only ever assignable during first-run onboarding, which left an
 * account that registered as Contributor with no way to ever act as an
 * Operator — the marketplace action simply 403'd with no route forward. This
 * panel is the durable home for that change: it reports the roles the account
 * holds and offers whichever self-assignable role is still missing.
 *
 * Attestor is absent by design — it is granted through an organization and
 * cannot be self-selected.
 *
 * Maps to: FR-AUTH-013, FR-SET-002.
 */
import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import {
  describeRole,
  RoleSelectionForm,
  SELF_ROLES,
  type SelfRole,
} from "@/components/modules/auth/role-selection-form";
import { loadCurrentUserSession } from "@/lib/auth/current-user-session";
import { toSafeInternalPath } from "@/lib/auth/onboarding";

import { FormMessage } from "../auth/form-message";

/**
 * Render the account's current roles and the picker for anything missing.
 */
export function AccountRolesPanel() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [roles, setRoles] = useState<string[]>([]);
  const [pendingRoles, setPendingRoles] = useState<string[]>([]);
  // Narrowed: it arrives from a query parameter and decides a navigation.
  const returnTo = toSafeInternalPath(
    useSearchParams()?.get("next") ?? undefined,
  );

  useEffect(() => {
    let mounted = true;

    async function loadRoles(): Promise<void> {
      const user = await loadCurrentUserSession();
      if (!mounted) return;
      setLoading(false);
      if (!user) {
        setError("The request could not be completed.");
        return;
      }
      setRoles(user.roles ?? []);
      setPendingRoles(user.pending_roles ?? []);
    }

    void loadRoles();
    return () => {
      mounted = false;
    };
  }, []);

  // A full navigation is the honest way to settle a role change: the nav, the
  // route guards and the landing page all branch on roles, and the access
  // token has just been reissued underneath them. When the user arrived from a
  // blocked action, return them to it — that is the whole point of the trip.
  const settleRoleChange = useCallback(() => {
    window.location.assign(returnTo ?? window.location.pathname);
  }, [returnTo]);

  if (loading) {
    return (
      <div className="rounded-xl border border-border-default bg-surface-2 px-4 py-3 text-sm text-foreground-muted">
        Loading account roles...
      </div>
    );
  }

  // `pending_roles` is disjoint from `roles` by contract, so the two lists can
  // be rendered side by side. Both count as held: a role already requested must
  // not be offered again, which would only 409.
  const heldRoles = new Set([...roles, ...pendingRoles]);
  const missingRoles = SELF_ROLES.filter((role) => !heldRoles.has(role));

  return (
    <section
      aria-labelledby="account-roles-heading"
      className="space-y-5"
      role="region"
    >
      <div>
        <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
          Roles
        </p>
        <h2
          className="mt-2 font-heading text-2xl font-bold text-foreground"
          id="account-roles-heading"
        >
          How you use Auracles
        </h2>
        <p className="mt-3 text-sm leading-6 text-foreground-muted">
          Roles decide which marketplace actions are open to your account.
          Contributors publish and sell Frameworks; Operators purchase them and
          post Projects. Holding both is normal.
        </p>
      </div>

      {error ? <FormMessage kind="error" message={error} /> : null}

      <div className="rounded-xl border border-border-default bg-surface-2 p-5">
        <h3 className="font-heading text-sm font-semibold text-foreground">
          Active on this account
        </h3>
        {roles.length === 0 && pendingRoles.length === 0 ? (
          <p className="mt-2 text-sm leading-6 text-foreground-muted">
            No roles yet.
          </p>
        ) : (
          <ul className="mt-3 flex flex-wrap gap-2">
            {roles.map((role) => (
              <li
                className="inline-flex items-center rounded-full border border-border-default bg-background px-3 py-1 text-sm font-medium text-foreground"
                key={role}
              >
                {describeRole(role)}
              </li>
            ))}
            {pendingRoles.map((role) => (
              <li
                className="inline-flex items-center rounded-full border border-accent/30 bg-accent/10 px-3 py-1 text-sm font-medium text-accent"
                key={`pending-${role}`}
              >
                {describeRole(role)} — awaiting approval
              </li>
            ))}
          </ul>
        )}
      </div>

      {missingRoles.length > 0 ? (
        <div className="rounded-xl border border-border-default bg-surface-2 p-5">
          <RoleSelectionForm
            availableRoles={missingRoles as SelfRole[]}
            description="Adding a role is immediate and does not affect the roles you already hold. Identity verification is not repeated."
            heading="Add a role"
            onSaved={settleRoleChange}
            submitLabel="Add role"
          />
        </div>
      ) : (
        <p className="rounded-xl border border-border-default bg-surface-2 px-5 py-4 text-sm leading-6 text-foreground-muted">
          You hold both marketplace roles. Attestor access is granted through an
          organization and cannot be added here.
        </p>
      )}
    </section>
  );
}
