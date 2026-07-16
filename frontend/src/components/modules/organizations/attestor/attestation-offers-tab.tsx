"use client";

import { useState, useEffect, useCallback } from "react";
import { useOrganization } from "@/components/modules/organizations/organization-context";
import { useRefetchOnFocus } from "@/lib/hooks/use-refetch-on-focus";
import { listOrgAttestationOffersV1OrgsOrgIdAttestationOffersGet } from "@/lib/generated/sdk.gen";
import { getAccessTokenHeaders, describeGeneratedError } from "@/lib/auth/form-client";
import { OrgAttestationOfferItem } from "@/lib/generated/types.gen";
import { declineOrgAttestationOfferV1OrgsOrgIdAttestationOffersOfferIdDeclinePost } from "@/lib/generated/sdk.gen";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { Badge } from "@/components/ui/badge";
import { AcceptAndStaffDialog } from "./accept-and-staff-dialog";

export function AttestationOffersTab() {
  const { orgId, role } = useOrganization();
  const [offers, setOffers] = useState<OrgAttestationOfferItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  
  const [acceptingOfferId, setAcceptingOfferId] = useState<string | null>(null);
  const [decliningId, setDecliningId] = useState<string | null>(null);

  async function load(isMounted: () => boolean) {
      setLoading(true);
      setError(null);
      const res = await listOrgAttestationOffersV1OrgsOrgIdAttestationOffersGet({
        path: { org_id: orgId! },
        headers: getAccessTokenHeaders(),
      });
      if (!isMounted()) return;
      setLoading(false);
      if (res.error) {
        setError(describeGeneratedError(res.error));
      } else if (res.data) {
        setOffers(res.data.offers);
      }
    }

  useEffect(() => {
    let mounted = true;
    if (!orgId) return;

    const doLoad = async () => {
      setLoading(true);
      await load(() => mounted);
      if (mounted) setLoading(false);
    };
    doLoad();
    return () => { mounted = false; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orgId]);

  // Silently refresh the offer list when the owner returns to the tab, so a new
  // cohort offer appears without a manual reload (no spinner flash).
  const refreshOffers = useCallback(async () => {
    if (!orgId) return;
    const res = await listOrgAttestationOffersV1OrgsOrgIdAttestationOffersGet({
      path: { org_id: orgId },
      headers: getAccessTokenHeaders(),
    });
    if (res.response.ok && res.data) {
      setOffers(res.data.offers);
    }
  }, [orgId]);
  useRefetchOnFocus(refreshOffers);

  async function handleDecline(offerId: string) {
    if (!orgId) return;
    if (!window.confirm("Are you sure you want to decline this offer?")) return;
    
    setDecliningId(offerId);
    setError(null);
    const res = await declineOrgAttestationOfferV1OrgsOrgIdAttestationOffersOfferIdDeclinePost({
      path: { org_id: orgId, offer_id: offerId },
      headers: getAccessTokenHeaders(),
    });
    setDecliningId(null);
    if (res.error) {
      setError(describeGeneratedError(res.error));
    } else {
      await load(() => true);
    }
  }

  if (loading) {
    return <div className="p-4 flex items-center gap-2 text-sm text-foreground-muted"><Spinner className="w-4 h-4" /> Loading offers...</div>;
  }

  if (error) {
    return <div className="p-4 text-sm text-error bg-error/5 border border-error/20 rounded-md">{error}</div>;
  }

  if (offers.length === 0) {
    return (
      <div className="p-8 text-center text-foreground-muted border border-border-default border-dashed rounded-xl bg-surface-2">
        <h3 className="font-semibold text-foreground mb-1">No Offers Available</h3>
        <p className="text-sm">There are currently no open attestation offers for this organization.</p>
      </div>
    );
  }

  const isAdmin = role === "admin" || role === "owner";

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center mb-6">
        <h2 className="text-xl font-semibold tracking-tight text-foreground">Attestation Offers</h2>
      </div>
      
      <div className="grid gap-4">
        {offers.map((offer) => {
          const expiresAt = new Date(offer.expires_at);
          const isExpired = expiresAt < new Date();
          
          return (
            <div key={offer.offer_id} className="border border-border-default rounded-xl p-5 bg-surface-1 shadow-sm flex flex-col md:flex-row md:items-center justify-between gap-4">
              <div className="space-y-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-semibold text-foreground">
                    {offer.target_title ?? (
                      <span className="capitalize">{offer.target_type}</span>
                    )}
                  </span>
                  <Badge variant="default" className="capitalize">
                    {offer.target_type}
                  </Badge>
                  <Badge variant={isExpired ? "error" : offer.status === "offered" ? "info" : "default"}>
                    {isExpired ? "expired" : offer.status}
                  </Badge>
                </div>
                <div className="text-xs text-foreground-muted font-mono">
                  Attestation ID: {offer.attestation_id}
                </div>
                <div className="text-sm text-foreground-muted">
                  Match Score: {offer.match_score ? `${offer.match_score}%` : "N/A"}
                </div>
                {!isExpired && (
                  <div className="text-xs font-medium text-amber-600 mt-2">
                    Expires: {expiresAt.toLocaleString()}
                  </div>
                )}
              </div>
              
              <div className="flex gap-2">
                <Button 
                  variant="secondary" 
                  disabled={isExpired || !isAdmin || decliningId === offer.offer_id}
                  onClick={() => handleDecline(offer.offer_id)}
                >
                  {decliningId === offer.offer_id ? "Declining..." : "Decline"}
                </Button>
                <Button 
                  disabled={isExpired || !isAdmin}
                  onClick={() => setAcceptingOfferId(offer.offer_id)}
                >
                  Accept
                </Button>
              </div>
            </div>
          );
        })}
      </div>

      {acceptingOfferId && orgId && (
        <AcceptAndStaffDialog
          orgId={orgId}
          offerId={acceptingOfferId}
          onClose={() => setAcceptingOfferId(null)}
          onDone={() => {
            setAcceptingOfferId(null);
            load(() => true);
          }}
        />
      )}
    </div>
  );
}
