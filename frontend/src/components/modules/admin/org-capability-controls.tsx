"use client";

/**
 * Suspend / reinstate / revoke controls for one organization capability.
 *
 * Works for the contributor, operator, and attestor capabilities so the
 * admin organizations directory and the attestor console share one set of
 * transitions and one confirm step. Each transition changes what every
 * member of the organization can do on the marketplace, so it confirms
 * through the shared dialog and requires an open step-up window (the API
 * answers 403 and the global prompt handles it). Suspend and revoke collect
 * a required reason that the organization's owner will see; reinstate does
 * not. Only the transitions valid for the current status are enabled.
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
  reinstateOrgContributorCapability,
  reinstateOrgOperatorCapability,
  revokeOrgAttestorCapability,
  revokeOrgContributorCapability,
  revokeOrgOperatorCapability,
  suspendOrgAttestorCapability,
  suspendOrgContributorCapability,
  suspendOrgOperatorCapability,
} from "@/lib/generated/sdk.gen";

/** Capabilities an organization can hold, as the API names them. */
export type OrgCapability = "contributor" | "operator" | "attestor";

export type CapabilityAction = "suspend" | "reinstate" | "revoke";

/** Resulting capability status after each transition. */
export type CapabilityStatusAfter = "active" | "suspended" | "revoked";

/** Human labels for each capability. */
export const CAPABILITY_LABELS: Record<OrgCapability, string> = {
  contributor: "Contributor",
  operator: "Operator",
  attestor: "Attestor",
};

type OrgCapabilityControlsProps = {
  orgId: string;
  orgName: string;
  capability: OrgCapability;
  /** Current capability status from the API. */
  status: string;
  /**
   * Called after a successful transition with the new status and the reason
   * sent (null for reinstate, which clears the stored reason).
   */
  onChanged: (status: CapabilityStatusAfter, reason: string | null) => void;
  onError: (message: string) => void;
};

type ActionCopy = { title: string; body: string; confirm: string };

const COPY: Record<OrgCapability, Record<CapabilityAction, ActionCopy>> = {
  contributor: {
    suspend: {
      title: "Suspend contributor capability?",
      body: "Members lose the Contributor role and the organization cannot publish or sell frameworks until reinstated.",
      confirm: "Suspend",
    },
    reinstate: {
      title: "Reinstate contributor capability?",
      body: "Members regain the Contributor role and the organization can publish and sell again.",
      confirm: "Reinstate",
    },
    revoke: {
      title: "Revoke contributor capability?",
      body: "This is permanent. The contributor profile is deactivated and members lose the Contributor role.",
      confirm: "Revoke",
    },
  },
  operator: {
    suspend: {
      title: "Suspend operator capability?",
      body: "Members lose the Operator role and the organization cannot purchase frameworks or post projects until reinstated.",
      confirm: "Suspend",
    },
    reinstate: {
      title: "Reinstate operator capability?",
      body: "Members regain the Operator role and the organization can purchase and post projects again.",
      confirm: "Reinstate",
    },
    revoke: {
      title: "Revoke operator capability?",
      body: "This is permanent. Members lose the Operator role and the organization must activate again from scratch.",
      confirm: "Revoke",
    },
  },
  attestor: {
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
  },
};

const RESULT: Record<CapabilityAction, CapabilityStatusAfter> = {
  suspend: "suspended",
  reinstate: "active",
  revoke: "revoked",
};

type CapabilityCall = (options: {
  body?: { reason: string };
  headers: Record<string, string>;
  path: { org_id: string };
}) => Promise<{ response: { ok: boolean }; error?: unknown }>;

/**
 * Resolve the SDK call for one capability transition.
 *
 * Looked up at call time rather than in a module-level table so surfaces
 * that only exercise one capability do not have to load the others' SDK
 * bindings.
 */
function resolveCall(capability: OrgCapability, action: CapabilityAction): CapabilityCall {
  let call: unknown;
  if (capability === "contributor") {
    call =
      action === "suspend"
        ? suspendOrgContributorCapability
        : action === "reinstate"
          ? reinstateOrgContributorCapability
          : revokeOrgContributorCapability;
  } else if (capability === "operator") {
    call =
      action === "suspend"
        ? suspendOrgOperatorCapability
        : action === "reinstate"
          ? reinstateOrgOperatorCapability
          : revokeOrgOperatorCapability;
  } else {
    call =
      action === "suspend"
        ? suspendOrgAttestorCapability
        : action === "reinstate"
          ? reinstateOrgAttestorCapability
          : revokeOrgAttestorCapability;
  }
  return call as CapabilityCall;
}

/**
 * Which transitions the backend accepts from a capability status.
 *
 * @param status - Current capability status, or null when never activated.
 */
export function capabilityTransitions(status: string | null | undefined) {
  return {
    canSuspend: status === "active",
    canReinstate: status === "suspended",
    canRevoke: status === "active" || status === "suspended",
  };
}

/**
 * Render the capability transition buttons with a confirm step.
 *
 * @param props - Organization identity, capability, current status, callbacks.
 */
export function OrgCapabilityControls({
  orgId,
  orgName,
  capability,
  status,
  onChanged,
  onError,
}: OrgCapabilityControlsProps) {
  const reasonFieldId = useId();
  const transitions = capabilityTransitions(status);
  const [pending, setPending] = useState<CapabilityAction | null>(null);
  const [busy, setBusy] = useState(false);
  // Owner-visible reason; required for suspend and revoke, so the confirm
  // button stays disabled until it satisfies the backend length rule.
  const [reason, setReason] = useState("");
  const needsReason = pending === "suspend" || pending === "revoke";
  const reasonMissing = needsReason && !isReasonValid(reason);
  const copy = pending ? COPY[capability][pending] : null;

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
    const trimmed = reason.trim();
    try {
      const call = resolveCall(capability, pending);
      const result = needsReason
        ? await call({ body: { reason: trimmed }, headers, path })
        : await call({ headers, path });
      if (!result.response.ok) {
        onError(describeGeneratedError(result.error));
        return;
      }
      onChanged(RESULT[pending], needsReason ? trimmed : null);
      setPending(null);
      setReason("");
    } catch {
      onError("The capability could not be updated.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="flex flex-wrap gap-2">
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
        confirmLabel={copy ? copy.confirm : "Confirm"}
        description={
          copy ? (
            <>
              <p>
                {orgName}: {copy.body}
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
        eyebrow={`${CAPABILITY_LABELS[capability]} capability`}
        onClose={close}
        onConfirm={() => void confirm()}
        open={pending !== null}
        title={copy ? copy.title : ""}
        tone={pending === "reinstate" ? "default" : "danger"}
      />
    </>
  );
}
