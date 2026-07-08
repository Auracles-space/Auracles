"use client";

import { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { ReviewingMemberPicker } from "./reviewing-member-picker";
import { acceptOrgAttestationOfferV1OrgsOrgIdAttestationOffersOfferIdAcceptPost } from "@/lib/generated/sdk.gen";
import { getAccessTokenHeaders, describeGeneratedError } from "@/lib/auth/form-client";

export type AcceptAndStaffDialogProps = {
  orgId: string;
  offerId: string;
  onDone: () => void;
  onClose: () => void;
};

export function AcceptAndStaffDialog({ orgId, offerId, onDone, onClose }: AcceptAndStaffDialogProps) {
  const [selectedMemberId, setSelectedMemberId] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        onClose();
      }
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  async function handleAccept() {
    if (!selectedMemberId) return;
    setIsSubmitting(true);
    setError(null);
    
    const res = await acceptOrgAttestationOfferV1OrgsOrgIdAttestationOffersOfferIdAcceptPost({
      path: { org_id: orgId, offer_id: offerId },
      body: { reviewing_member_id: selectedMemberId },
      headers: getAccessTokenHeaders(),
    });

    setIsSubmitting(false);

    if (res.error) {
      setError(describeGeneratedError(res.error));
    } else {
      onDone();
    }
  }

  return (
    <div
      aria-modal="true"
      className="fixed inset-0 z-50 grid place-items-end bg-black/40 p-0 motion-safe:animate-[fade-in_120ms_ease-out] sm:place-items-center sm:p-4"
      onClick={onClose}
      role="dialog"
    >
      <div
        className="w-full rounded-t-2xl border border-border-default bg-surface-1 p-5 shadow-xl sm:max-w-md sm:rounded-2xl"
        onClick={(event) => event.stopPropagation()}
      >
        <h2 className="mt-1 font-heading text-xl font-bold text-foreground">
          Accept Offer & Assign
        </h2>
        <div className="mt-2 text-sm text-foreground-muted">
          Choose a member of your organization to assign as the Reviewing Member for this attestation. They must have signed the NDA and have capacity.
        </div>

        <div className="py-4 space-y-4">
          {error && (
            <div className="p-3 text-sm text-error bg-error/5 border border-error/20 rounded-md">
              {error}
            </div>
          )}
          <ReviewingMemberPicker
            orgId={orgId}
            value={selectedMemberId}
            onChange={setSelectedMemberId}
          />
        </div>

        <div className="mt-2 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button variant="secondary" onClick={onClose} disabled={isSubmitting}>
            Cancel
          </Button>
          <Button 
            onClick={handleAccept} 
            disabled={!selectedMemberId || isSubmitting} 
            loading={isSubmitting}
          >
            Accept Offer
          </Button>
        </div>
      </div>
    </div>
  );
}
