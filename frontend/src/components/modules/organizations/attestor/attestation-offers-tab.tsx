"use client";

import { useState, useEffect } from "react";
import { useOrganization } from "@/components/modules/organizations/organization-context";
import { listOrgAttestationOffersV1OrgsOrgIdAttestationOffersGet } from "@/lib/generated/sdk.gen";
import { getAccessTokenHeaders, describeGeneratedError } from "@/lib/auth/form-client";
import { OrgAttestationOfferItem } from "@/lib/generated/types.gen";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { Badge } from "@/components/ui/badge";

export function AttestationOffersTab() {
  const { orgId, role } = useOrganization();
  const [offers, setOffers] = useState<OrgAttestationOfferItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;
    if (!orgId) return;

    async function load() {
      setLoading(true);
      setError(null);
      const res = await listOrgAttestationOffersV1OrgsOrgIdAttestationOffersGet({
        path: { org_id: orgId! },
        headers: getAccessTokenHeaders(),
      });
      if (!mounted) return;
      setLoading(false);
      if (res.error) {
        setError(describeGeneratedError(res.error));
      } else if (res.data) {
        setOffers(res.data.offers);
      }
    }
    load();
    return () => { mounted = false; };
  }, [orgId]);

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
                <div className="flex items-center gap-2">
                  <span className="font-medium text-foreground capitalize">{offer.target_type}</span>
                  <Badge variant={isExpired ? "error" : offer.status === "offered" ? "info" : "default"}>
                    {isExpired ? "expired" : offer.status}
                  </Badge>
                </div>
                <div className="text-sm text-foreground-muted font-mono">
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
                {/* Stubs for Accept and Decline functionality to be wired in Task 11 */}
                <Button variant="secondary" disabled={isExpired || !isAdmin}>
                  Decline
                </Button>
                <Button disabled={isExpired || !isAdmin}>
                  Accept
                </Button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
