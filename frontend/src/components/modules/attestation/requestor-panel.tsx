"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import { TableSkeleton } from "@/components/ui/skeletons/table-skeleton";
import { Textarea } from "@/components/ui/textarea";
import { Select } from "@/components/ui/select";
import {
  CHECKOUT_COUNTRIES,
  defaultBillingCountry,
} from "@/lib/marketplace/countries";
import { JURISDICTION_OPTIONS } from "@/lib/marketplace/taxonomy";
import {
  acceptAttestationReport,
  createAttestationDispute,
  listAttestations,
  listContributorFrameworks,
  requestAttestation,
} from "@/lib/generated/sdk.gen";
import type {
  AttestationRequestResponse,
  FrameworkListItem,
} from "@/lib/generated/types.gen";
import { isNonEmpty } from "@/lib/forms/validators";
import {
  AttestationCard,
  ErrorMessage,
  HeaderCard,
} from "@/components/modules/attestation/attestation-status";
import { AttestationFundingPanel } from "@/components/modules/attestation/attestation-funding-panel";

export function RequestorPanel() {
  const [attestations, setAttestations] = useState<AttestationRequestResponse[]>([]);
  const [disputeReason, setDisputeReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [targetId, setTargetId] = useState("");
  const [myFrameworks, setMyFrameworks] = useState<FrameworkListItem[]>([]);
  const [reviewType, setReviewType] = useState<
    "" | "quality" | "compliance" | "expert" | "provenance"
  >("");
  const [whatItDoes, setWhatItDoes] = useState("");
  const [useCase, setUseCase] = useState("");
  const [jurisdiction, setJurisdiction] = useState("");
  const [focusAreas, setFocusAreas] = useState("");
  const [desiredOutcome, setDesiredOutcome] = useState("");
  const [isRequesting, setIsRequesting] = useState(false);
  // Billing country drives the payment rail (Nigeria pays the fee through
  // Paystack hosted checkout), so it is shown and editable, never inferred.
  const [country, setCountry] = useState(defaultBillingCountry);
  const [fundingSession, setFundingSession] = useState<{
    attestationId: string;
    clientSecret: string;
  } | null>(null);
  // Attestation is framework-only today; the request always targets a Framework
  // and the backend requires a review type plus a fully-populated brief.
  const canRequest =
    isNonEmpty(targetId) &&
    isNonEmpty(reviewType) &&
    isNonEmpty(whatItDoes) &&
    isNonEmpty(useCase) &&
    isNonEmpty(jurisdiction) &&
    isNonEmpty(focusAreas) &&
    isNonEmpty(desiredOutcome);
  const canDispute = isNonEmpty(disputeReason);

  useEffect(() => {
    void loadRequestorAttestations();
    void loadMyFrameworks();
  }, []);

  /**
   * Load the requester's own frameworks to populate the framework target picker.
   *
   * Failure is non-fatal: the picker simply shows no options, and the request
   * form surfaces its own error when a target is not selected.
   */
  async function loadMyFrameworks() {
    configureBrowserClient();
    const result = await listContributorFrameworks({
      headers: getAccessTokenHeaders(),
    });
    if (result.response.ok && result.data) {
      setMyFrameworks(result.data);
    }
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
      const attestations = await loadRequestorAttestations();
      const target = attestations?.find(
        (item: AttestationRequestResponse) => item.id === attestationId,
      );
      if (!target || target.status !== "pending_fee") {
        return;
      }
      await new Promise((resolve) => setTimeout(resolve, 2000));
    }
  }

  /**
   * Create a new escrow-funded Attestation request.
   */
  async function handleRequestAttestation() {
    setError(null);
    setIsRequesting(true);
    let redirecting = false;
    try {
      configureBrowserClient();
      const result = await requestAttestation({
        body: {
          target_type: "framework",
          target_id: targetId,
          review_type: reviewType || null,
          brief: {
            what_it_does: whatItDoes,
            use_case: useCase,
            jurisdiction,
            focus_areas: focusAreas,
            desired_outcome: desiredOutcome,
          },
          country,
        },
        headers: getAccessTokenHeaders(),
      });
      if (!result.response.ok || !result.data) {
        setError(describeGeneratedError(result.error));
        return;
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
        return;
      }
      setTargetId("");
      setReviewType("");
      setWhatItDoes("");
      setUseCase("");
      setJurisdiction("");
      setFocusAreas("");
      setDesiredOutcome("");
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
    } finally {
      // Stay in the requesting state through a Paystack navigation so the
      // button cannot be pressed twice into two charges.
      if (!redirecting) {
        setIsRequesting(false);
      }
    }
  }

  /**
   * Accept a submitted report and release escrow.
   *
   * @param attestationId - Attestation UUID.
   */
  async function handleAcceptReport(attestationId: string) {
    setError(null);
    configureBrowserClient();
    const result = await acceptAttestationReport({
      headers: getAccessTokenHeaders(),
      path: { attestation_id: attestationId },
    });
    if (!result.response.ok || !result.data) {
      setError(describeGeneratedError(result.error));
      return;
    }
    setAttestations((current) =>
      current.map((item) => (item.id === attestationId ? result.data : item)),
    );
  }

  /**
   * Raise a dispute against a submitted report.
   *
   * @param attestationId - Attestation UUID.
   */
  async function handleDispute(attestationId: string) {
    setError(null);
    configureBrowserClient();
    const result = await createAttestationDispute({
      body: { reason: disputeReason, category: "scope_error" },
      headers: getAccessTokenHeaders(),
      path: { attestation_id: attestationId },
    });
    if (!result.response.ok) {
      setError(describeGeneratedError(result.error));
      return;
    }
    setDisputeReason("");
    await loadRequestorAttestations();
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

      <details
        className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm"
        open={attestations.length === 0}
      >
        <summary className="cursor-pointer font-heading text-xl font-bold text-foreground">
          Request Attestation
        </summary>
        <div className="mt-4 grid gap-4 md:grid-cols-2">
          <label className="grid gap-2 text-sm font-semibold text-foreground">
            <span>Framework <span className="text-error">*</span></span>
            <Select
              onChange={(event) => setTargetId(event.target.value)}
              value={targetId}
            >
              <option value="">Select a framework</option>
              {myFrameworks.map((framework) => (
                <option key={framework.id} value={framework.id}>
                  {framework.title}
                </option>
              ))}
            </Select>
          </label>
          <label className="grid gap-2 text-sm font-semibold text-foreground">
            <span>Review type <span className="text-error">*</span></span>
            <Select
              onChange={(event) =>
                setReviewType(
                  event.target.value as
                    | ""
                    | "quality"
                    | "compliance"
                    | "expert"
                    | "provenance",
                )
              }
              value={reviewType}
            >
              <option value="">Select a review type</option>
              <option value="quality">Quality</option>
              <option value="compliance">Compliance</option>
              <option value="expert">Expert</option>
              <option value="provenance">Provenance</option>
            </Select>
          </label>
        </div>

        <p className="mt-6 text-sm font-semibold text-foreground">
          Review brief
        </p>
        <p className="mt-1 text-sm text-foreground-muted">
          The attestor cohort sees this brief when deciding whether to take the
          review.
        </p>
        <div className="mt-3 grid gap-4">
          <label className="grid gap-2 text-sm font-semibold text-foreground">
            <span>What it does <span className="text-error">*</span></span>
            <Textarea
              onChange={(event) => setWhatItDoes(event.target.value)}
              placeholder="What the framework does and the problem it solves."
              value={whatItDoes}
            />
          </label>
          <label className="grid gap-2 text-sm font-semibold text-foreground">
            <span>Use case <span className="text-error">*</span></span>
            <Textarea
              onChange={(event) => setUseCase(event.target.value)}
              placeholder="Who uses it and in what situation."
              value={useCase}
            />
          </label>
          <label className="grid gap-2 text-sm font-semibold text-foreground">
            <span>Jurisdiction <span className="text-error">*</span></span>
            <Select
              onChange={(event) => setJurisdiction(event.target.value)}
              value={jurisdiction}
            >
              <option value="">Select a jurisdiction</option>
              {JURISDICTION_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </Select>
          </label>
          <label className="grid gap-2 text-sm font-semibold text-foreground">
            <span>Focus areas <span className="text-error">*</span></span>
            <Textarea
              onChange={(event) => setFocusAreas(event.target.value)}
              placeholder="What the review should scrutinise most."
              value={focusAreas}
            />
          </label>
          <label className="grid gap-2 text-sm font-semibold text-foreground">
            <span>Desired outcome <span className="text-error">*</span></span>
            <Textarea
              onChange={(event) => setDesiredOutcome(event.target.value)}
              placeholder="What a successful attestation looks like for you."
              value={desiredOutcome}
            />
          </label>
          <label className="grid gap-2 text-sm font-semibold text-foreground">
            <span>Billing country</span>
            <Select
              disabled={isRequesting}
              onChange={(event) => setCountry(event.target.value)}
              value={country}
            >
              {CHECKOUT_COUNTRIES.map((option) => (
                <option key={option.code} value={option.code}>
                  {option.name}
                </option>
              ))}
            </Select>
            <span className="text-xs font-normal leading-5 text-foreground-muted">
              Determines how your fee payment is processed.
            </span>
          </label>
        </div>
        <button
          className="mt-6 min-h-12 rounded-xl bg-foreground px-6 text-sm font-semibold text-background shadow-sm outline-none transition hover:bg-foreground/90 focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-60"
          disabled={!canRequest || isRequesting}
          onClick={handleRequestAttestation}
          type="button"
        >
          {isRequesting ? "Requesting…" : "Request attestation"}
        </button>
      </details>

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
          <AttestationCard attestation={attestation} key={attestation.id}>
            <div className="mt-4">
              <Link
                className="text-sm font-semibold text-accent hover:underline"
                href={`/attestations/${attestation.id}`}
              >
                View details
              </Link>
            </div>
            {attestation.status === "report_submitted" ? (
              <div className="mt-4 grid gap-3">
                <button
                  className="min-h-12 rounded-xl bg-foreground px-6 text-sm font-semibold text-background shadow-sm outline-none transition-colors hover:bg-foreground/90 focus-visible:ring-2 focus-visible:ring-accent"
                  onClick={() => handleAcceptReport(attestation.id)}
                  type="button"
                >
                  Accept report
                </button>
                <label className="grid gap-2 text-sm font-semibold text-foreground">
                  Dispute reason
                  <Textarea
                    
                    onChange={(event) => setDisputeReason(event.target.value)}
                    value={disputeReason}
                  />
                </label>
                <button
                  className="min-h-12 rounded-xl border border-error/50 bg-error/5 px-6 text-sm font-semibold text-error outline-none transition-colors hover:bg-error/10 focus-visible:ring-2 focus-visible:ring-error disabled:cursor-not-allowed disabled:opacity-60"
                  disabled={!canDispute}
                  onClick={() => handleDispute(attestation.id)}
                  type="button"
                >
                  Raise dispute
                </button>
              </div>
            ) : null}
          </AttestationCard>
        ))}
      </div>
    </section>
  );
}
