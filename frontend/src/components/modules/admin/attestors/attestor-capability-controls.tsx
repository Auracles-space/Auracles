"use client";

/**
 * Suspend / reinstate / revoke controls for an approved attestor capability.
 *
 * Each transition changes what every member of the organization can do on
 * the marketplace, so it confirms through the shared dialog and requires an
 * open step-up window (the API answers 403 and the global prompt handles it).
 * Only the transitions valid for the current status are enabled.
 */
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import {
  reinstateOrgAttestorCapability,
  revokeOrgAttestorCapability,
  suspendOrgAttestorCapability,
} from "@/lib/generated/sdk.gen";

import type { CapabilityTransitions } from "./attestor-gates";

export type CapabilityAction = "suspend" | "reinstate" | "revoke";

type AttestorCapabilityControlsProps = {
  orgId: string;
  orgName: string;
  transitions: CapabilityTransitions;
  /** Called with the new capability status after a successful transition. */
  onChanged: (status: "active" | "suspended" | "revoked") => void;
  onError: (message: string) => void;
};

const COPY: Record<CapabilityAction, { title: string; body: string; confirm: string }> = {
  suspend: {
    title: "Suspend attestor capability?",
    body: "The organization stops receiving offers and its members lose the Attestor role until reinstated.",
    confirm: "Suspend",
  },
  reinstate: {
    title: "Reinstate attestor capability?",
    body: "The organization becomes matchable again and its members regain the Attestor role.",
    confirm: "Reinstate",
  },
  revoke: {
    title: "Revoke attestor capability?",
    body: "This is permanent. The organization must apply again from scratch to attest.",
    confirm: "Revoke",
  },
};

const RESULT: Record<CapabilityAction, "active" | "suspended" | "revoked"> = {
  suspend: "suspended",
  reinstate: "active",
  revoke: "revoked",
};

/**
 * Render the capability transition buttons with a confirm step.
 *
 * @param props - Organization identity, allowed transitions, callbacks.
 */
export function AttestorCapabilityControls({
  orgId,
  orgName,
  transitions,
  onChanged,
  onError,
}: AttestorCapabilityControlsProps) {
  const [pending, setPending] = useState<CapabilityAction | null>(null);
  const [busy, setBusy] = useState(false);

  async function confirm() {
    if (!pending) {
      return;
    }
    setBusy(true);
    configureBrowserClient();
    const call =
      pending === "suspend"
        ? suspendOrgAttestorCapability
        : pending === "reinstate"
          ? reinstateOrgAttestorCapability
          : revokeOrgAttestorCapability;
    try {
      const result = await call({
        headers: getAccessTokenHeaders(),
        path: { org_id: orgId },
      });
      if (!result.response.ok) {
        onError(describeGeneratedError(result.error));
        return;
      }
      onChanged(RESULT[pending]);
      setPending(null);
    } catch {
      onError("The capability could not be updated.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-xl border border-border-default bg-surface-2 p-4">
      <p className="text-xs font-semibold uppercase tracking-[0.05em] text-foreground-muted">
        Capability controls
      </p>
      <div className="mt-3 flex flex-wrap gap-2">
        <Button
          disabled={!transitions.canSuspend || busy}
          onClick={() => setPending("suspend")}
          variant="destructive"
        >
          Suspend
        </Button>
        <Button
          disabled={!transitions.canReinstate || busy}
          onClick={() => setPending("reinstate")}
          variant="secondary"
        >
          Reinstate
        </Button>
        <Button
          disabled={!transitions.canRevoke || busy}
          onClick={() => setPending("revoke")}
          variant="destructive"
        >
          Revoke
        </Button>
      </div>

      <ConfirmDialog
        busy={busy}
        confirmLabel={pending ? COPY[pending].confirm : "Confirm"}
        description={pending ? `${orgName}: ${COPY[pending].body}` : ""}
        eyebrow="Attestor capability"
        onClose={() => (busy ? undefined : setPending(null))}
        onConfirm={() => void confirm()}
        open={pending !== null}
        title={pending ? COPY[pending].title : ""}
        tone={pending === "reinstate" ? "default" : "danger"}
      />
    </div>
  );
}
