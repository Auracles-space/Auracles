"use client";

/**
 * Suspend / reinstate / revoke controls for an approved attestor capability.
 *
 * Each transition changes what every member of the organization can do on
 * the marketplace, so it confirms through the shared dialog and requires an
 * open step-up window (the API answers 403 and the global prompt handles it).
 * Suspend and revoke also collect a required reason that the organization's
 * owner will see; reinstate does not. Only the transitions valid for the
 * current status are enabled.
 */
import { useId, useState } from "react";

import { ReasonField, isReasonValid } from "@/components/modules/admin/reason-field";
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
  const reasonFieldId = useId();
  const [pending, setPending] = useState<CapabilityAction | null>(null);
  const [busy, setBusy] = useState(false);
  // Owner-visible reason; required for suspend and revoke, so the confirm
  // button stays disabled until it satisfies the backend length rule.
  const [reason, setReason] = useState("");
  const needsReason = pending === "suspend" || pending === "revoke";
  const reasonMissing = needsReason && !isReasonValid(reason);

  /** Open the confirm dialog for one transition with a fresh reason field. */
  function open(action: CapabilityAction) {
    setReason("");
    setPending(action);
  }

  /** Dismiss the dialog and drop any half-typed reason. */
  function close() {
    if (busy) {
      return;
    }
    setPending(null);
    setReason("");
  }

  async function confirm() {
    if (!pending || reasonMissing) {
      return;
    }
    setBusy(true);
    configureBrowserClient();
    const headers = getAccessTokenHeaders();
    const path = { org_id: orgId };
    try {
      const result =
        pending === "reinstate"
          ? await reinstateOrgAttestorCapability({ headers, path })
          : pending === "suspend"
            ? await suspendOrgAttestorCapability({
                body: { reason: reason.trim() },
                headers,
                path,
              })
            : await revokeOrgAttestorCapability({
                body: { reason: reason.trim() },
                headers,
                path,
              });
      if (!result.response.ok) {
        onError(describeGeneratedError(result.error));
        return;
      }
      onChanged(RESULT[pending]);
      setPending(null);
      setReason("");
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
          onClick={() => open("suspend")}
          variant="destructive"
        >
          Suspend
        </Button>
        <Button
          disabled={!transitions.canReinstate || busy}
          onClick={() => open("reinstate")}
          variant="secondary"
        >
          Reinstate
        </Button>
        <Button
          disabled={!transitions.canRevoke || busy}
          onClick={() => open("revoke")}
          variant="destructive"
        >
          Revoke
        </Button>
      </div>

      <ConfirmDialog
        busy={busy || reasonMissing}
        confirmLabel={pending ? COPY[pending].confirm : "Confirm"}
        description={
          pending ? (
            <>
              <p>
                {orgName}: {COPY[pending].body}
              </p>
              {needsReason ? (
                <ReasonField
                  disabled={busy}
                  id={reasonFieldId}
                  onChange={setReason}
                  value={reason}
                />
              ) : null}
            </>
          ) : (
            ""
          )
        }
        eyebrow="Attestor capability"
        onClose={close}
        onConfirm={() => void confirm()}
        open={pending !== null}
        title={pending ? COPY[pending].title : ""}
        tone={pending === "reinstate" ? "default" : "danger"}
      />
    </div>
  );
}
