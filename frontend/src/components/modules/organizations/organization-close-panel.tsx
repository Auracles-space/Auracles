"use client";

/**
 * Close-organization panel (owner-only, step-up gated on the API).
 *
 * Deactivation is a soft close (Decision 4): the organization is closed and
 * hidden, its data is retained, members are notified, and an administrator
 * can reopen it. The API refuses the close with 409 while a capability is
 * active or money is pending; that server message is shown verbatim. An
 * optional reason travels with the request for the audit row and the
 * member notification.
 *
 * Maps to: docs/superpowers/specs/2026-09-14-organizations-end-to-end-design.md
 * §Decisions 4, §Slice B.
 */
import { useState } from "react";
import { useRouter } from "next/navigation";

import { deactivateOrganizationV1OrgsOrgIdDelete } from "@/lib/generated/sdk.gen";
import { describeGeneratedError, getAccessTokenHeaders } from "@/lib/auth/form-client";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { useOrganization } from "./organization-context";

const REASON_MAX_LENGTH = 500;

/**
 * Render the close-organization card and its typed-confirmation dialog.
 */
export function OrganizationClosePanel() {
  const { orgId, org, role, isSuspended } = useOrganization();
  const isOwner = role === "owner";
  const router = useRouter();

  const [showDialog, setShowDialog] = useState(false);
  const [confirmText, setConfirmText] = useState("");
  const [reason, setReason] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const expectedConfirmText = `Close ${org.name}`;
  const confirmed = confirmText === expectedConfirmText;

  function closeDialog(): void {
    setShowDialog(false);
    setConfirmText("");
    setReason("");
  }

  async function handleClose(): Promise<void> {
    if (!isOwner || isSuspended || !confirmed) return;

    setLoading(true);
    setError(null);

    try {
      const trimmedReason = reason.trim();
      const result = await deactivateOrganizationV1OrgsOrgIdDelete({
        path: { org_id: orgId },
        headers: getAccessTokenHeaders(),
        ...(trimmedReason ? { body: { reason: trimmedReason } } : {}),
      });

      if (!result.response.ok) {
        // A 409 carries the server's own explanation of what is still
        // active or pending; every other failure reads the same way.
        setError(describeGeneratedError(result.error));
        setLoading(false);
        closeDialog();
        return;
      }
      router.push("/dashboard/organizations");
    } catch (caught) {
      setError(describeGeneratedError(caught));
      setLoading(false);
      closeDialog();
    }
  }

  return (
    <div className="rounded-2xl border border-error/50 bg-error/5 p-6">
      <h2 className="mb-2 font-heading text-xl font-bold text-error">Close organization</h2>
      <p className="mb-6 text-sm leading-6 text-foreground" data-testid="close-organization-copy">
        The organization is closed and hidden from the marketplace. Its data is
        retained, members are notified, and an administrator can reopen it.
        Closing is blocked while a capability is active or money is pending.
      </p>

      {error && (
        <div
          className="mb-4 rounded-xl border border-error bg-error/10 p-4 text-sm font-semibold text-error"
          role="alert"
        >
          {error}
        </div>
      )}

      <Button
        className="min-h-11"
        disabled={isSuspended}
        onClick={() => setShowDialog(true)}
        variant="destructive"
      >
        Close organization
      </Button>

      <ConfirmDialog
        open={showDialog}
        title="Close organization"
        description={
          <div className="flex flex-col gap-4">
            <p>
              {org.name} will be closed and hidden. Its data is retained, members
              are notified, and an administrator can reopen it later.
            </p>
            <div>
              <label className="mb-1 block text-sm font-semibold text-foreground" htmlFor="close-reason">
                Reason (optional)
              </label>
              <Textarea
                className="min-h-24"
                id="close-reason"
                maxLength={REASON_MAX_LENGTH}
                onChange={(event) => setReason(event.target.value)}
                placeholder="Shared with members and kept on the audit trail."
                value={reason}
              />
              <p className="mt-1 text-xs text-foreground-muted">
                {reason.length}/{REASON_MAX_LENGTH}
              </p>
            </div>
            <p>
              To confirm, type{" "}
              <strong className="select-all rounded bg-surface-2 px-1 py-0.5 text-foreground">
                {expectedConfirmText}
              </strong>{" "}
              below:
            </p>
            <Input
              aria-label="Confirmation phrase"
              onChange={(event) => setConfirmText(event.target.value)}
              placeholder={expectedConfirmText}
              value={confirmText}
            />
          </div>
        }
        confirmLabel="Close"
        tone="danger"
        busy={loading}
        confirmDisabled={!confirmed}
        onConfirm={handleClose}
        onClose={closeDialog}
      />
    </div>
  );
}
