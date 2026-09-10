"use client";

/**
 * Org capability activation card.
 *
 * Lets an org owner/admin self-activate the Contributor and Operator
 * capabilities. Each activation grants every member the derived role, so the
 * action is gated behind a confirm dialog. Attestor is intentionally excluded:
 * it has its own application and NDA front-door.
 *
 * Maps to: test-guide OC-1, OO-1.
 */
import { useState } from "react";
import { useRouter } from "next/navigation";

import { getAccessTokenHeaders } from "@/lib/auth/form-client";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { useToast } from "@/components/ui/toast";
import {
  activateContributorCapabilityV1OrgsOrgIdContributorCapabilityActivatePost as activateContributor,
  activateOperatorCapabilityV1OrgsOrgIdOperatorCapabilityActivatePost as activateOperator,
} from "@/lib/generated/sdk.gen";
import { useOrganization } from "./organization-context";

type CapabilityKey = "contributor" | "operator";

type CapabilityMeta = {
  key: CapabilityKey;
  label: string;
  description: string;
};

const CAPABILITIES: CapabilityMeta[] = [
  {
    key: "contributor",
    label: "Contributor",
    description: "Create and sell frameworks under the organization's identity.",
  },
  {
    key: "operator",
    label: "Operator",
    description: "Purchase frameworks and post projects as the organization.",
  },
];

/** Render a status pill for a capability's current state. */
function StatusPill({ status }: { status?: string }) {
  if (status === "active") {
    return (
      <span className="rounded-md border border-success/30 bg-success/10 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.05em] text-success">
        Active
      </span>
    );
  }

  if (status === "suspended") {
    return (
      <span className="rounded-md border border-warning/30 bg-warning/10 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.05em] text-warning">
        Suspended
      </span>
    );
  }

  return (
    <span className="rounded-md border border-border-default bg-surface-2 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.05em] text-foreground-muted">
      Not active
    </span>
  );
}

/**
 * Card of self-service capability rows for organization owners and admins.
 */
export function OrganizationCapabilities() {
  const { orgId, role, capabilities, kybStatus, isSuspended, refreshOrganization } =
    useOrganization();
  const router = useRouter();
  const toast = useToast();

  const [pending, setPending] = useState<CapabilityKey | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isAdminOrOwner = role === "owner" || role === "admin";
  if (!isAdminOrOwner || isSuspended) {
    return null;
  }

  const pendingMeta = CAPABILITIES.find((cap) => cap.key === pending) ?? null;

  function openConfirm(key: CapabilityKey) {
    setError(null);
    setPending(key);
  }

  function closeConfirm() {
    if (busy) {
      return;
    }

    setPending(null);
    setError(null);
  }

  async function handleConfirm() {
    if (!pendingMeta) {
      return;
    }

    setBusy(true);
    setError(null);

    try {
      const result =
        pendingMeta.key === "contributor"
          ? await activateContributor({
              path: { org_id: orgId },
              headers: getAccessTokenHeaders(),
            })
          : await activateOperator({
              path: { org_id: orgId },
              headers: getAccessTokenHeaders(),
            });

      if (!result.response.ok) {
        setError(
          result.error?.detail?.error_code ||
            `Failed to activate ${pendingMeta.label} capability`,
        );
        return;
      }

      await refreshOrganization();
      toast.success(`${pendingMeta.label} capability activated.`);
      setPending(null);
      router.refresh();
    } catch {
      setError("An unexpected error occurred.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="max-w-3xl overflow-hidden rounded-3xl border border-border-default bg-surface-1 shadow-sm">
      <div className="border-b border-border-default bg-surface-2/50 px-8 py-6">
        <h2 className="font-heading text-xl font-bold tracking-tight text-foreground">
          Capabilities
        </h2>
        <p className="mt-1 text-sm text-foreground-muted">
          Activate what your organization can do on the marketplace. Members
          receive each right through the teams you assign it to.
        </p>
      </div>

      <ul className="flex flex-col divide-y divide-border-default">
        {CAPABILITIES.map((cap) => (
          <li
            key={cap.key}
            className="flex flex-col gap-3 px-8 py-5 sm:flex-row sm:items-center sm:justify-between"
          >
            <div>
              <p className="text-sm font-semibold text-foreground">{cap.label}</p>
              <p className="mt-0.5 text-sm text-foreground-muted">
                {cap.description}
              </p>
            </div>
            <div className="flex items-center gap-3">
              <StatusPill status={capabilities?.[cap.key]} />
              {capabilities?.[cap.key] !== "active" &&
              capabilities?.[cap.key] !== "suspended" ? (
                kybStatus === "verified" ? (
                  <button
                    type="button"
                    aria-label={`Activate ${cap.label} capability`}
                    onClick={() => openConfirm(cap.key)}
                    className="min-h-11 rounded-xl bg-foreground px-5 py-2 text-sm font-semibold text-background shadow-sm transition hover:bg-foreground/90"
                  >
                    Activate
                  </button>
                ) : (
                  // The API refuses activation for an unverified org, so a
                  // live Activate button here would only manufacture a 403.
                  <a
                    className="inline-flex min-h-11 items-center rounded-xl border border-border-default bg-surface-2 px-5 py-2 text-sm font-semibold text-foreground-muted transition hover:bg-surface-3"
                    href={`/dashboard/organizations/${orgId}/verification`}
                  >
                    Verify to activate
                  </a>
                )
              ) : null}
            </div>
          </li>
        ))}
      </ul>

      <ConfirmDialog
        open={pendingMeta !== null}
        eyebrow="Capability"
        title={pendingMeta ? `Activate ${pendingMeta.label} capability?` : ""}
        description={
          pendingMeta
            ? `Unlocks the ${pendingMeta.label} capability for the organization. You then grant it to members by enabling it on their teams. Owners and admins hold it immediately.`
            : ""
        }
        confirmLabel={pendingMeta ? `Activate ${pendingMeta.label}` : "Activate"}
        busy={busy}
        error={error}
        onConfirm={handleConfirm}
        onClose={closeConfirm}
      />
    </section>
  );
}
