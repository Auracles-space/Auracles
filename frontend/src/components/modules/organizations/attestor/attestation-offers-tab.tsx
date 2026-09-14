"use client";

/**
 * Open attestation offers for one attestor organization.
 *
 * One card per offer, carrying what the org is being asked to review, how well
 * the matcher scored it, and how long is left to answer — the clock is the
 * whole point of this tab, since an unanswered offer lapses to the next
 * cohort. Accepting opens the staffing dialog; declining goes through a
 * confirm step with an optional, admin-only reason.
 *
 * Maps to: docs/superpowers/specs/2026-09-14-attestation-request-to-report-design.md §2
 * (Attestor org).
 */

import Link from "next/link";
import { useState, useEffect, useCallback } from "react";

import { useOrganization } from "@/components/modules/organizations/organization-context";
import { useRefetchOnFocus } from "@/lib/hooks/use-refetch-on-focus";
import { listOrgAttestationOffersV1OrgsOrgIdAttestationOffersGet } from "@/lib/generated/sdk.gen";
import { getAccessTokenHeaders, describeGeneratedError } from "@/lib/auth/form-client";
import { OrgAttestationOfferItem } from "@/lib/generated/types.gen";
import { formatLabel } from "@/lib/marketplace/format";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { StatusPill, offerStatusKey } from "@/components/ui/status-pill";
import { AcceptAndStaffDialog } from "./accept-and-staff-dialog";
import { DeclineOfferDialog } from "./decline-offer-dialog";
import { describeOfferExpiry } from "./attestation-dates";

/**
 * Render the matcher's score as a whole percentage.
 *
 * The API sends a 0–1 float, and a genuine zero is a real score (a cohort
 * offer the matcher rated poorly), so it must not be confused with a missing
 * one.
 *
 * @param score - Match score between 0 and 1, or null when unscored.
 */
function describeMatchScore(score: number | null): string {
  if (score === null || score === undefined) {
    return "No score";
  }
  return `${Math.round(score * 100)}% match`;
}

/**
 * List and action the organization's attestation offers.
 */
export function AttestationOffersTab() {
  const { orgId, role } = useOrganization();
  const [offers, setOffers] = useState<OrgAttestationOfferItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [acceptingOfferId, setAcceptingOfferId] = useState<string | null>(null);
  const [decliningOfferId, setDecliningOfferId] = useState<string | null>(null);

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

  if (loading) {
    return <div className="p-4 flex items-center gap-2 text-sm text-foreground-muted"><Spinner className="w-4 h-4" /> Loading offers...</div>;
  }

  if (error) {
    return <div className="p-4 text-sm text-error bg-error/5 border border-error/20 rounded-md">{error}</div>;
  }

  if (offers.length === 0) {
    return (
      <div className="p-8 text-center text-foreground-muted border border-border-default border-dashed rounded-xl bg-surface-2">
        <h3 className="font-semibold text-foreground mb-1">No offers available</h3>
        <p className="text-sm">There are currently no open attestation offers for this organization.</p>
      </div>
    );
  }

  const isAdmin = role === "admin" || role === "owner";

  return (
    <div className="space-y-4">
      <h2 className="text-xl font-semibold tracking-tight text-foreground">
        Attestation offers
      </h2>

      <div className="grid gap-4">
        {offers.map((offer) => {
          const expiry = describeOfferExpiry(offer.expires_at);
          // Accept/decline only make sense on a live, un-actioned offer. Once
          // accepted (member staffed) or expired, show status only.
          const isActionable = offer.status === "offered" && !expiry.expired;
          // A lapsed offer still reads `offered` server-side until the sweeper
          // runs; the pill says what it actually is, so no countdown line is
          // repeated underneath it.
          const pillStatus =
            expiry.expired && offer.status === "offered"
              ? "expired"
              : offerStatusKey(offer.status);

          return (
            <article
              className="flex flex-col gap-4 rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm md:flex-row md:items-center md:justify-between"
              key={offer.offer_id}
            >
              <div className="space-y-2">
                <div className="flex flex-wrap items-center gap-2">
                  <h3 className="font-heading text-base font-bold text-foreground">
                    {offer.target_title ?? formatLabel(offer.target_type)}
                  </h3>
                  <StatusPill status={pillStatus} />
                </div>
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-foreground-muted">
                  {offer.target_title ? (
                    <>
                      <span>{formatLabel(offer.target_type)}</span>
                      <span aria-hidden="true">·</span>
                    </>
                  ) : null}
                  <span>{describeMatchScore(offer.match_score)}</span>
                </div>
                {expiry.expired ? null : (
                  <p className="text-sm font-medium text-warning">{expiry.label}</p>
                )}
              </div>

              {isActionable ? (
                <div className="flex flex-col gap-2 sm:flex-row">
                  <Button
                    disabled={!isAdmin}
                    onClick={() => setDecliningOfferId(offer.offer_id)}
                    variant="destructive"
                  >
                    Decline
                  </Button>
                  <Button
                    disabled={!isAdmin}
                    onClick={() => setAcceptingOfferId(offer.offer_id)}
                  >
                    Accept
                  </Button>
                </div>
              ) : offer.status === "accepted" ? (
                <Link
                  className="inline-flex min-h-12 items-center justify-center rounded-xl border border-border-default bg-surface-1 px-6 text-sm font-semibold text-foreground transition-colors hover:bg-surface-2"
                  href={`/dashboard/organizations/${orgId}/attestations/${offer.attestation_id}`}
                >
                  Open workspace
                </Link>
              ) : null}
            </article>
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

      {decliningOfferId && orgId && (
        <DeclineOfferDialog
          offerId={decliningOfferId}
          onClose={() => setDecliningOfferId(null)}
          onDone={() => {
            setDecliningOfferId(null);
            load(() => true);
          }}
          orgId={orgId}
        />
      )}
    </div>
  );
}
