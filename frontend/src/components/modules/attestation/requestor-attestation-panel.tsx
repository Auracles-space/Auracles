"use client";

import { useEffect, useState } from "react";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import { TableSkeleton } from "@/components/ui/skeletons/table-skeleton";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Select } from "@/components/ui/select";
import {
  acceptAttestationReport,
  createAttestationDispute,
  listAttestations,
  requestAttestation,
} from "@/lib/generated/sdk.gen";
import type { AttestationRequestResponse } from "@/lib/generated/types.gen";
import { allValid, isNonEmpty } from "@/lib/forms/validators";
import {
  AttestationCard,
  ErrorMessage,
  HeaderCard,
  splitCsv,
} from "@/components/modules/attestation/attestation-workspaces";

export function AttestationRequestorPanel() {
  const [attestations, setAttestations] = useState<AttestationRequestResponse[]>([]);
  const [disputeReason, setDisputeReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [jurisdictions, setJurisdictions] = useState("");
  const [loading, setLoading] = useState(true);
  const [specializations, setSpecializations] = useState("");
  const [targetId, setTargetId] = useState("");
  const [targetType, setTargetType] =
    useState<"framework" | "contributor" | "operator" | "credential">("framework");
  const canRequest = allValid(
    isNonEmpty(targetId),
    isNonEmpty(specializations),
    isNonEmpty(jurisdictions),
  );
  const canDispute = isNonEmpty(disputeReason);

  useEffect(() => {
    void loadRequestorAttestations();
  }, []);

  /**
   * Load requestor-visible Attestations.
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
      return;
    }
    setAttestations(result.data.attestations);
    setLoading(false);
  }

  /**
   * Create a new escrow-funded Attestation request.
   */
  async function handleRequestAttestation() {
    setError(null);
    configureBrowserClient();
    const result = await requestAttestation({
      body: {
        requested_jurisdictions: splitCsv(jurisdictions),
        requested_specializations: splitCsv(specializations),
        target_id: targetId,
        target_type: targetType,
      },
      headers: getAccessTokenHeaders(),
    });
    if (!result.response.ok || !result.data) {
      setError(describeGeneratedError(result.error));
      return;
    }
    setTargetId("");
    await loadRequestorAttestations();
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

      <div className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
        <h2 className="font-heading text-xl font-bold text-foreground">
          Request Attestation
        </h2>
        <div className="mt-4 grid gap-4 md:grid-cols-2">
          <label className="grid gap-2 text-sm font-semibold text-foreground">
            Target type
            <Select
              
              onChange={(event) =>
                setTargetType(
                  event.target.value as
                    | "framework"
                    | "contributor"
                    | "operator"
                    | "credential",
                )
              }
              value={targetType}
            >
              <option value="framework">Framework</option>
              <option value="contributor">Contributor profile</option>
              <option value="operator">Operator organization</option>
              <option value="credential">Credential</option>
            </Select>
          </label>
          <label className="grid gap-2 text-sm font-semibold text-foreground">
            Target ID
            <Input
              
              onChange={(event) => setTargetId(event.target.value)}
              value={targetId}
            />
          </label>
          <label className="grid gap-2 text-sm font-semibold text-foreground">
            Specializations
            <Input
              
              onChange={(event) => setSpecializations(event.target.value)}
              placeholder="governance, healthcare"
              value={specializations}
            />
          </label>
          <label className="grid gap-2 text-sm font-semibold text-foreground">
            Jurisdictions
            <Input
              
              onChange={(event) => setJurisdictions(event.target.value)}
              placeholder="US, EU"
              value={jurisdictions}
            />
          </label>
        </div>
        <button
          className="mt-6 min-h-12 rounded-xl bg-foreground px-6 text-sm font-semibold text-background shadow-sm outline-none transition hover:bg-foreground/90 focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-60"
          disabled={!canRequest}
          onClick={handleRequestAttestation}
          type="button"
        >
          Start fee escrow
        </button>
      </div>

      <div className="grid gap-3">
        {attestations.map((attestation) => (
          <AttestationCard attestation={attestation} key={attestation.id}>
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
