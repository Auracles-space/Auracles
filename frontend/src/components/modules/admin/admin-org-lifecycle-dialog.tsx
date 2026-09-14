"use client";

/**
 * Confirm dialog for an organization-wide lifecycle action in the admin
 * directory: suspend, reinstate, or reactivate a closed organization.
 *
 * Suspending removes every member's derived marketplace roles at once, so it
 * collects a required reason the owner will see; reinstate and reactivate are
 * body-less. The API requires an open step-up window, which the browser
 * client's interceptor prompts for; any other refusal is shown inside the
 * dialog via `describeGeneratedError`. The parent mounts this only while a
 * target is selected, so a half-typed reason never leaks to the next target.
 *
 * Maps to: organizations end-to-end design, Slice D (directory) and Decision 4.
 */
import { useId, useState } from "react";
import {
  adminReactivateOrgV1AdminOrgsOrgIdReactivatePost,
  adminReinstateOrgV1AdminOrgsOrgIdReinstatePost,
  adminSuspendOrgV1AdminOrgsOrgIdSuspendPost,
} from "@/lib/generated/sdk.gen";
import type { AdminOrgResponse } from "@/lib/generated/types.gen";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { ReasonField, isReasonValid } from "@/components/modules/admin/reason-field";
import type { OrgDirectoryAction } from "@/components/modules/admin/admin-org-directory-entry";

type AdminOrgLifecycleDialogProps = {
  /** Organization the action targets. */
  org: AdminOrgResponse;
  /** Which lifecycle action to confirm. */
  kind: OrgDirectoryAction;
  /** Dismiss without acting. */
  onClose: () => void;
  /** Called after the API confirms the action; the parent reloads its page. */
  onDone: () => void | Promise<void>;
};

const TITLES: Record<OrgDirectoryAction, string> = {
  suspend: "Suspend Organization?",
  reinstate: "Reinstate Organization?",
  reactivate: "Reactivate Organization?",
};

const CONFIRM_LABELS: Record<OrgDirectoryAction, string> = {
  suspend: "Suspend",
  reinstate: "Reinstate",
  reactivate: "Reactivate",
};

/**
 * Confirm and perform one lifecycle action on an organization.
 *
 * @param org - Target organization.
 * @param kind - Suspend, reinstate, or reactivate.
 * @param onClose - Dismiss handler.
 * @param onDone - Success handler.
 */
export function AdminOrgLifecycleDialog({ org, kind, onClose, onDone }: AdminOrgLifecycleDialogProps) {
  const reasonFieldId = useId();
  const [reason, setReason] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Owner-visible reason is required for suspend only, so confirm stays
  // disabled until it satisfies the backend length rule.
  const reasonMissing = kind === "suspend" && !isReasonValid(reason);

  async function handleConfirm() {
    if (reasonMissing) return;
    setLoading(true);
    setError(null);
    configureBrowserClient();
    try {
      const target = { path: { org_id: org.id }, headers: getAccessTokenHeaders() };
      const result =
        kind === "suspend"
          ? await adminSuspendOrgV1AdminOrgsOrgIdSuspendPost({ ...target, body: { reason: reason.trim() } })
          : kind === "reinstate"
            ? await adminReinstateOrgV1AdminOrgsOrgIdReinstatePost(target)
            : await adminReactivateOrgV1AdminOrgsOrgIdReactivatePost(target);
      setLoading(false);
      if (!result.response.ok) {
        setError(describeGeneratedError(result.error));
        return;
      }
      await onDone();
    } catch (caught) {
      setError(describeGeneratedError(caught));
      setLoading(false);
    }
  }

  const description =
    kind === "suspend" ? (
      <>
        <p>
          Are you sure you want to suspend &quot;{org.name}&quot;? Members will lose access to
          organization resources immediately.
        </p>
        <ReasonField disabled={loading} id={reasonFieldId} onChange={setReason} value={reason} />
      </>
    ) : kind === "reinstate" ? (
      `Reinstate "${org.name}"? Members will regain access to organization resources immediately.`
    ) : (
      `Reopen ${org.name}? Members regain access; the owner is notified.`
    );

  return (
    <ConfirmDialog
      open
      title={TITLES[kind]}
      description={description}
      confirmLabel={CONFIRM_LABELS[kind]}
      tone={kind === "suspend" ? "danger" : "default"}
      busy={loading || reasonMissing}
      error={error}
      onConfirm={handleConfirm}
      onClose={onClose}
    />
  );
}
