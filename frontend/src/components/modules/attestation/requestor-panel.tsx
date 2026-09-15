"use client";

/**
 * Requestor Attestation workspace.
 *
 * Holds the request form and the list of the requestor's own requests. A
 * `target` query parameter — set by the "Request attestation" links on the
 * framework workspace and the public framework page — opens the form expanded
 * with that framework pinned, so the owner-consent path for a framework the
 * requestor does not own is reachable at all.
 *
 * Maps to: docs/superpowers/specs/2026-09-14-attestation-request-to-report-design.md §2.
 */
import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";

import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import { TableSkeleton } from "@/components/ui/skeletons/table-skeleton";
import {
  getExploreFrameworkDetail,
  listAttestations,
  listContributorFrameworks,
  requestAttestation,
} from "@/lib/generated/sdk.gen";
import type {
  AttestationRequestResponse,
  FrameworkListItem,
} from "@/lib/generated/types.gen";
import {
  ErrorMessage,
  HeaderCard,
} from "@/components/modules/attestation/attestation-status";
import { AttestationFundingPanel } from "@/components/modules/attestation/attestation-funding-panel";
import {
  AttestationRequestForm,
  type AttestationRequestDraft,
} from "@/components/modules/attestation/attestation-request-form";
import { RequestorAttestationCard } from "@/components/modules/attestation/requestor-attestation-card";

/**
 * Render the requestor Attestation workspace.
 */
export function RequestorPanel() {
  const target = useSearchParams()?.get("target") ?? null;
  const [attestations, setAttestations] = useState<AttestationRequestResponse[]>(
    [],
  );
  const [pinned, setPinned] = useState<{
    id: string;
    title: string;
    external: boolean;
  } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [myFrameworks, setMyFrameworks] = useState<FrameworkListItem[]>([]);
  const [isRequesting, setIsRequesting] = useState(false);
  const [fundingSession, setFundingSession] = useState<{
    attestationId: string;
    clientSecret: string;
  } | null>(null);

  useEffect(() => {
    void bootstrap();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [target]);

  /**
   * Load the workspace and resolve the pinned framework, if any.
   *
   * The requestor's own frameworks are checked first so a self-request needs
   * no extra call; anything else is read from the public framework endpoint,
   * which is the only source of a title for a framework they do not own. The
   * pin is resolved before the list renders so the form never flips its
   * heading under the requestor.
   */
  async function bootstrap() {
    const own = await loadMyFrameworks();
    if (target) {
      const mine = own.find((framework) => framework.id === target);
      if (mine) {
        setPinned({ id: target, title: mine.title, external: false });
      } else {
        const result = await getExploreFrameworkDetail({
          path: { framework_id: target },
        });
        setPinned({
          id: target,
          title:
            result.response.ok && result.data
              ? result.data.title
              : "This framework",
          external: true,
        });
      }
    }
    await loadRequestorAttestations();
  }

  /**
   * Load the requester's own frameworks to populate the framework target picker.
   *
   * Failure is non-fatal: the picker simply shows no options, and the request
   * form keeps its submit disabled until a target is selected.
   *
   * @returns The requestor's frameworks, or an empty list on failure.
   */
  async function loadMyFrameworks(): Promise<FrameworkListItem[]> {
    configureBrowserClient();
    const result = await listContributorFrameworks({
      headers: getAccessTokenHeaders(),
    });
    if (result.response.ok && result.data) {
      setMyFrameworks(result.data);
      return result.data;
    }
    return [];
  }

  /**
   * Load requestor-visible Attestations.
   *
   * @returns The loaded attestations, or null when the request failed.
   */
  async function loadRequestorAttestations() {
    configureBrowserClient();
    const result = await listAttestations({
      headers: getAccessTokenHeaders(),
      query: { role: "requestor" },
    });
    if (!result.response.ok || !result.data) {
      setError(describeGeneratedError(result.error));
      setLoading(false);
      return null;
    }
    setAttestations(result.data.attestations);
    setLoading(false);
    return result.data.attestations;
  }

  /**
   * Poll a just-paid request until it leaves ``pending_fee``.
   *
   * The fee moves the request forward via an async Stripe webhook, so a single
   * reload right after payment races it. Reload immediately, then retry a few
   * times so the status updates without a manual refresh.
   *
   * @param attestationId - The funded attestation to watch.
   */
  async function pollFundedStatus(attestationId: string) {
    for (let attempt = 0; attempt < 6; attempt += 1) {
      const loaded = await loadRequestorAttestations();
      const funded = loaded?.find(
        (item: AttestationRequestResponse) => item.id === attestationId,
      );
      if (!funded || funded.status !== "pending_fee") {
        return;
      }
      await new Promise((resolve) => setTimeout(resolve, 2000));
    }
  }

  /**
   * Create a new escrow-funded Attestation request.
   *
   * @param draft - The completed request form.
   * @returns True when the form should clear itself.
   */
  async function handleRequestAttestation(
    draft: AttestationRequestDraft,
  ): Promise<boolean> {
    setError(null);
    setIsRequesting(true);
    let redirecting = false;
    try {
      configureBrowserClient();
      const result = await requestAttestation({
        body: {
          target_type: "framework",
          target_id: draft.targetId,
          review_type: draft.reviewType || null,
          brief: draft.brief,
          country: draft.country,
        },
        headers: getAccessTokenHeaders(),
      });
      if (!result.response.ok || !result.data) {
        setError(describeGeneratedError(result.error));
        return false;
      }
      const data = result.data;
      // Paystack owns the next screen: navigate to its hosted checkout and
      // keep the requesting state through navigation so the button cannot be
      // pressed twice into two charges.
      if (
        "authorization_url" in data &&
        data.provider === "paystack" &&
        data.authorization_url
      ) {
        redirecting = true;
        window.location.assign(data.authorization_url);
        return false;
      }
      // A requestor funding their own framework gets a PaymentIntent secret
      // back; surface the inline fee payment. A non-owner request instead
      // awaits owner consent and has no secret yet.
      if ("client_secret" in data && data.client_secret) {
        setFundingSession({
          attestationId: data.id,
          clientSecret: data.client_secret,
        });
      }
      await loadRequestorAttestations();
      return true;
    } finally {
      // Stay in the requesting state through a Paystack navigation so the
      // button cannot be pressed twice into two charges.
      if (!redirecting) {
        setIsRequesting(false);
      }
    }
  }

  if (loading) {
    return <TableSkeleton />;
  }

  return (
    <section className="grid gap-6">
      <HeaderCard
        eyebrow="Requestor workspace"
        title="Attestation requests"
        summary="Request independent verification, inspect reports, accept outcomes, or dispute within the open window."
      />
      <ErrorMessage message={error} />

      <AttestationRequestForm
        defaultOpen={Boolean(target) || attestations.length === 0}
        inFlight={attestations}
        myFrameworks={myFrameworks}
        onSubmit={handleRequestAttestation}
        pinned={pinned}
        submitting={isRequesting}
      />

      {fundingSession && (
        <AttestationFundingPanel
          attestationId={fundingSession.attestationId}
          clientSecret={fundingSession.clientSecret}
          onCancel={() => setFundingSession(null)}
          onPaid={() => {
            const paidId = fundingSession.attestationId;
            setFundingSession(null);
            void pollFundedStatus(paidId);
          }}
        />
      )}

      <div className="grid gap-3">
        <h2 className="font-heading text-xl font-bold text-foreground">
          Your requests
          {attestations.length > 0 ? ` (${attestations.length})` : ""}
        </h2>
        {attestations.length === 0 ? (
          <p className="rounded-2xl border border-border-default bg-surface-1 p-6 text-sm text-foreground-muted shadow-sm">
            You have not requested any attestations yet. Open “Request
            Attestation” above to start one.
          </p>
        ) : null}
        {attestations.map((attestation) => (
          <RequestorAttestationCard
            attestation={attestation}
            key={attestation.id}
          />
        ))}
      </div>
    </section>
  );
}
