"use client";

/**
 * Names the attestations already in progress for a framework, beside the
 * "Request attestation" link in the framework workspace.
 *
 * A framework may hold one in-flight request per review type. Without this
 * note the link looked the same with a review running, so a requestor picked
 * the same review type again and only learned of the duplicate on submit.
 * Reads the viewer's own requests; failure is silent because the note is a
 * hint and the server still refuses a duplicate.
 *
 * Maps to: docs/superpowers/specs/2026-09-14-attestation-request-to-report-design.md §2.
 */
import Link from "next/link";
import { useEffect, useState } from "react";

import { configureBrowserClient, getAccessTokenHeaders } from "@/lib/auth/form-client";
import { listAttestations } from "@/lib/generated/sdk.gen";
import type { AttestationRequestResponse } from "@/lib/generated/types.gen";
import { REVIEW_TYPE_LABELS, inFlightAttestationsFor } from "@/lib/attestation/in-flight";

/**
 * Render one link per in-progress attestation of the framework.
 *
 * @param frameworkId - The framework whose requests to show.
 */
export function InFlightAttestationNotes({ frameworkId }: { frameworkId: string }) {
  const [running, setRunning] = useState<AttestationRequestResponse[]>([]);

  useEffect(() => {
    let active = true;
    async function load() {
      configureBrowserClient();
      const result = await listAttestations({
        headers: getAccessTokenHeaders(),
        query: { role: "requestor" },
      });
      if (!active || !result.response.ok || !result.data) return;
      setRunning(inFlightAttestationsFor(result.data.attestations, frameworkId));
    }
    void load();
    return () => {
      active = false;
    };
  }, [frameworkId]);

  if (running.length === 0) {
    return null;
  }

  return (
    <>
      {running.map((attestation) => (
        <Link
          className="inline-flex min-h-12 items-center rounded-xl px-2 text-sm font-semibold text-accent outline-none hover:underline focus-visible:ring-2 focus-visible:ring-accent"
          href={`/attestations/${attestation.id}`}
          key={attestation.id}
        >
          {REVIEW_TYPE_LABELS[attestation.review_type ?? ""] ?? "Attestation"} review in
          progress · View
        </Link>
      ))}
    </>
  );
}
