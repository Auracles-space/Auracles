"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { 
  listMembersV1OrgsOrgIdMembersGet,
  transferOwnershipV1OrgsOrgIdTransferOwnershipPost,
  deactivateOrganizationV1OrgsOrgIdDelete
} from "@/lib/generated/sdk.gen";
import type { OrgMemberResponse } from "@/lib/generated/types.gen";
import { getAccessTokenHeaders } from "@/lib/auth/form-client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { useOrganization } from "./organization-context";
import { Spinner } from "@/components/ui/spinner";

export function OrganizationDangerZone() {
  const { orgId, org, role, isSuspended } = useOrganization();
  const isOwner = role === "owner";
  const router = useRouter();

  const [members, setMembers] = useState<OrgMemberResponse[]>([]);
  const [loadingMembers, setLoadingMembers] = useState(true);

  // Transfer State
  const [transferMemberId, setTransferMemberId] = useState("");
  const [transferTotp, setTransferTotp] = useState("");
  const [transferLoading, setTransferLoading] = useState(false);
  const [transferError, setTransferError] = useState<string | null>(null);

  // Deactivate State
  const [showDeactivateDialog, setShowDeactivateDialog] = useState(false);
  const [deactivateConfirmText, setDeactivateConfirmText] = useState("");
  const [deactivateLoading, setDeactivateLoading] = useState(false);
  const [deactivateError, setDeactivateError] = useState<string | null>(null);

  useEffect(() => {
    if (!isOwner) return;

    async function fetchMembers() {
      try {
        const result = await listMembersV1OrgsOrgIdMembersGet({
          path: { org_id: orgId },
          headers: getAccessTokenHeaders(),
        });
        if (result.response.ok && result.data) {
          // Exclude self from potential new owners
          setMembers(result.data.filter((m: any) => m.role !== "owner"));
        }
      } catch (err) {
        // Ignore error for now
      } finally {
        setLoadingMembers(false);
      }
    }
    fetchMembers();
  }, [orgId, isOwner]);

  async function handleTransfer(e: React.FormEvent) {
    e.preventDefault();
    if (!isOwner || isSuspended || !transferMemberId || !transferTotp) return;

    setTransferLoading(true);
    setTransferError(null);

    try {
      const result = await transferOwnershipV1OrgsOrgIdTransferOwnershipPost({
        path: { org_id: orgId },
        body: { new_owner_member_id: transferMemberId, totp_code: transferTotp },
        headers: getAccessTokenHeaders(),
      });

      if (!result.response.ok) {
        setTransferError(result.error?.detail?.error_code || "Failed to transfer ownership.");
        setTransferLoading(false);
      } else {
        // Successfully transferred ownership -> refresh page to see new role
        router.refresh();
        window.location.reload();
      }
    } catch (err) {
      setTransferError("An unexpected error occurred during transfer.");
      setTransferLoading(false);
    }
  }

  async function handleDeactivate() {
    const expectedConfirmText = `Delete ${org.name}`;
    if (!isOwner || isSuspended || deactivateConfirmText !== expectedConfirmText) return;

    setDeactivateLoading(true);
    setDeactivateError(null);

    try {
      const result = await deactivateOrganizationV1OrgsOrgIdDelete({
        path: { org_id: orgId },
        headers: getAccessTokenHeaders(),
      });

      if (!result.response.ok) {
        setDeactivateError(result.error?.detail?.error_code || "Failed to deactivate organization.");
        setDeactivateLoading(false);
        setShowDeactivateDialog(false);
      } else {
        router.push("/dashboard/organizations");
      }
    } catch (err) {
      setDeactivateError("An unexpected error occurred during deactivation.");
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

  const expectedConfirmText = `Delete ${org.name}`;
  const isDeactivateConfirmValid = deactivateConfirmText === expectedConfirmText;

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
          <div className="mb-4 rounded-xl border border-error/50 bg-error/5 p-4 text-sm text-error">
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
            ) : (
              <Select
                id="newOwner"
                disabled={isSuspended}
                value={transferMemberId}
                onChange={(e) => setTransferMemberId(e.target.value)}
              >
                <option value="">Select a member...</option>
                {members.map((m: any) => (
                  <option key={m.id} value={m.id}>
                    {m.display_name} ({m.email})
                  </option>
                ))}
              </Select>
            )}
          </div>

          <div>
            <label htmlFor="totp" className="mb-1 block text-sm font-semibold text-foreground">
              6-Digit Authenticator Code
            </label>
            <Input
              id="totp"
              required
              disabled={isSuspended || !transferMemberId}
              value={transferTotp}
              onChange={(e) => setTransferTotp(e.target.value)}
              placeholder="123456"
              maxLength={6}
            />
          </div>

          <Button 
            type="submit" 
            variant="primary"
            loading={transferLoading} 
            disabled={isSuspended || !transferMemberId || transferTotp.length < 6} 
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
          <div className="mb-4 rounded-xl border border-error bg-error/10 p-4 text-sm text-error font-semibold">
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
              value={deactivateConfirmText}
              onChange={(e) => setDeactivateConfirmText(e.target.value)}
              placeholder={expectedConfirmText}
            />
          </div>
        }
        confirmLabel="Deactivate"
        tone="danger"
        busy={deactivateLoading}
        onConfirm={handleDeactivate}
        onClose={() => {
          setShowDeactivateDialog(false);
          setDeactivateConfirmText("");
        }}
        // Prevent default confirm if text doesn't match by intercepting, 
        // but ConfirmDialog triggers `onConfirm` when confirm button clicked.
        // We can just check `isDeactivateConfirmValid` inside `handleDeactivate`
        // Wait, ConfirmDialog doesn't let us disable the button easily unless it supports it.
        // We will just do the check in `handleDeactivate`.
      />
    </div>
  );
}
