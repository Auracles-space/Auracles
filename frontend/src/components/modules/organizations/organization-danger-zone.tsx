"use client";

/**
 * Organization danger zone — owner-only ownership transfer and deactivation.
 *
 * Both actions are step-up gated on the API; this component only collects
 * the choice (new owner, typed confirmation phrase) and surfaces server
 * errors through `describeGeneratedError`.
 *
 * Maps to: FR-ORG ownership transfer and deactivation (spec §Slice A).
 */
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  listMembersV1OrgsOrgIdMembersGet,
  transferOwnershipV1OrgsOrgIdTransferOwnershipPost,
  deactivateOrganizationV1OrgsOrgIdDelete,
} from "@/lib/generated/sdk.gen";
import type { OrgMemberResponse } from "@/lib/generated/types.gen";
import { describeGeneratedError, getAccessTokenHeaders } from "@/lib/auth/form-client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { useOrganization } from "./organization-context";
import { Spinner } from "@/components/ui/spinner";

/**
 * Render the transfer-ownership form and the deactivate-organization guard.
 *
 * Non-owners see a single denial line; owners see both panels. The member
 * select excludes the current owner because transferring to oneself is a
 * no-op the API rejects.
 */
export function OrganizationDangerZone() {
  const { orgId, org, role, isSuspended } = useOrganization();
  const isOwner = role === "owner";
  const router = useRouter();

  const [members, setMembers] = useState<OrgMemberResponse[]>([]);
  const [loadingMembers, setLoadingMembers] = useState(true);
  const [membersError, setMembersError] = useState<string | null>(null);

  const [transferMemberId, setTransferMemberId] = useState("");
  const [transferLoading, setTransferLoading] = useState(false);
  const [transferError, setTransferError] = useState<string | null>(null);

  const [showDeactivateDialog, setShowDeactivateDialog] = useState(false);
  const [deactivateConfirmText, setDeactivateConfirmText] = useState("");
  const [deactivateLoading, setDeactivateLoading] = useState(false);
  const [deactivateError, setDeactivateError] = useState<string | null>(null);

  useEffect(() => {
    if (!isOwner) return;

    async function fetchMembers() {
      setMembersError(null);
      try {
        const result = await listMembersV1OrgsOrgIdMembersGet({
          path: { org_id: orgId },
          headers: getAccessTokenHeaders(),
        });
        if (result.response.ok && result.data) {
          setMembers(result.data.members.filter((m: OrgMemberResponse) => m.role !== "owner"));
        } else {
          setMembersError(describeGeneratedError(result.error));
        }
      } catch (error) {
        setMembersError(describeGeneratedError(error));
      } finally {
        setLoadingMembers(false);
      }
    }
    fetchMembers();
  }, [orgId, isOwner]);

  async function handleTransfer(e: React.FormEvent) {
    e.preventDefault();
    if (!isOwner || isSuspended || !transferMemberId) return;

    setTransferLoading(true);
    setTransferError(null);

    try {
      const result = await transferOwnershipV1OrgsOrgIdTransferOwnershipPost({
        path: { org_id: orgId },
        body: { new_owner_member_id: transferMemberId },
        headers: getAccessTokenHeaders(),
      });

      if (!result.response.ok) {
        setTransferError(describeGeneratedError(result.error));
        setTransferLoading(false);
      } else {
        // The caller is no longer the owner, so the whole org shell
        // (navigation, role gates) must re-render from the server.
        router.refresh();
        window.location.reload();
      }
    } catch (error) {
      setTransferError(describeGeneratedError(error));
      setTransferLoading(false);
    }
  }

  const expectedConfirmText = `Delete ${org.name}`;
  const deactivateConfirmed = deactivateConfirmText === expectedConfirmText;

  async function handleDeactivate() {
    if (!isOwner || isSuspended || !deactivateConfirmed) return;

    setDeactivateLoading(true);
    setDeactivateError(null);

    try {
      const result = await deactivateOrganizationV1OrgsOrgIdDelete({
        path: { org_id: orgId },
        headers: getAccessTokenHeaders(),
      });

      if (!result.response.ok) {
        setDeactivateError(describeGeneratedError(result.error));
        setDeactivateLoading(false);
        setShowDeactivateDialog(false);
      } else {
        router.push("/dashboard/organizations");
      }
    } catch (error) {
      setDeactivateError(describeGeneratedError(error));
      setDeactivateLoading(false);
      setShowDeactivateDialog(false);
    }
  }

  if (!isOwner) {
    return (
      <div className="rounded-2xl border border-error/50 bg-error/5 p-6 text-center text-error">
        Only the organization owner can view this page.
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-8 max-w-4xl">
      {/* Transfer Ownership */}
      <div className="rounded-2xl border border-border-default bg-surface-1 shadow-sm p-6">
        <h2 className="mb-2 font-heading text-xl font-bold text-foreground">
          Transfer Ownership
        </h2>
        <p className="mb-6 text-sm text-foreground-muted">
          Transfer ownership of this organization to another member. This action requires two-factor authentication.
        </p>

        {transferError && (
          <div className="mb-4 rounded-xl border border-error/50 bg-error/5 p-4 text-sm text-error" role="alert">
            {transferError}
          </div>
        )}

        <form onSubmit={handleTransfer} className="flex flex-col gap-4 max-w-sm">
          <div>
            <label htmlFor="newOwner" className="mb-1 block text-sm font-semibold text-foreground">
              New Owner
            </label>
            {loadingMembers ? (
              <Spinner className="h-6 w-6 text-accent" />
            ) : membersError ? (
              <p className="text-sm text-error" role="alert">
                {membersError}
              </p>
            ) : (
              <Select
                id="newOwner"
                disabled={isSuspended}
                value={transferMemberId}
                onChange={(e) => setTransferMemberId(e.target.value)}
              >
                <option value="">Select a member...</option>
                {members.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.display_name} ({m.email})
                  </option>
                ))}
              </Select>
            )}
          </div>

          <Button
            type="submit"
            variant="primary"
            loading={transferLoading}
            disabled={isSuspended || !transferMemberId}
            className="mt-2"
          >
            Transfer Ownership
          </Button>
        </form>
      </div>

      {/* Deactivate Organization */}
      <div className="rounded-2xl border border-error/50 bg-error/5 p-6">
        <h2 className="mb-2 font-heading text-xl font-bold text-error">
          Deactivate Organization
        </h2>
        <p className="mb-6 text-sm text-error/80">
          This will permanently delete the organization and all its data. This action cannot be undone.
          You can only deactivate the organization if there are no active capabilities or escrow funds.
        </p>

        {deactivateError && (
          <div className="mb-4 rounded-xl border border-error bg-error/10 p-4 text-sm text-error font-semibold" role="alert">
            {deactivateError}
          </div>
        )}

        <Button
          variant="destructive"
          disabled={isSuspended}
          onClick={() => setShowDeactivateDialog(true)}
        >
          Deactivate Organization
        </Button>
      </div>

      <ConfirmDialog
        open={showDeactivateDialog}
        title="Deactivate Organization"
        description={
          <div className="flex flex-col gap-4">
            <p>
              This action is irreversible. All data, members, and teams will be permanently deleted.
            </p>
            <p>
              To confirm, type <strong className="select-all bg-surface-2 px-1 py-0.5 rounded text-foreground">{expectedConfirmText}</strong> below:
            </p>
            <Input
              aria-label="Confirmation phrase"
              value={deactivateConfirmText}
              onChange={(e) => setDeactivateConfirmText(e.target.value)}
              placeholder={expectedConfirmText}
            />
          </div>
        }
        confirmLabel="Deactivate"
        tone="danger"
        busy={deactivateLoading}
        confirmDisabled={!deactivateConfirmed}
        onConfirm={handleDeactivate}
        onClose={() => {
          setShowDeactivateDialog(false);
          setDeactivateConfirmText("");
        }}
      />
    </div>
  );
}
