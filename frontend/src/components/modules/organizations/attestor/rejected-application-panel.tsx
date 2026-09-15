"use client";

/**
 * Start-again panel for a rejected attestor application.
 *
 * Rejection is not final: a fresh draft is opened seeded from the rejected
 * answers so the owner revises rather than retypes.
 */
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { describeGeneratedError, getAccessTokenHeaders } from "@/lib/auth/form-client";
import { createOrgAttestorApplication } from "@/lib/generated/sdk.gen";
import type { OrgAttestorApplicationResponse } from "@/lib/generated/types.gen";

/**
 * Body of the Apply gate after a rejection: explains that rejection is not
 * final and opens a fresh draft seeded from the rejected answers.
 *
 * @param application - The rejected application whose answers seed the draft.
 * @param orgId - Organization the new draft belongs to.
 * @param onStarted - Called once the draft exists so the tab reloads.
 */
export function RejectedApplicationPanel({
  application,
  orgId,
  onStarted,
}: {
  application: OrgAttestorApplicationResponse;
  orgId: string;
  onStarted: () => void;
}) {
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  /** Create a new draft carrying the previous answers forward. */
  async function handleStart() {
    setStarting(true);
    setError(null);
    try {
      const res = await createOrgAttestorApplication({
        path: { org_id: orgId },
        body: {
          credentials_summary: application.credentials_summary,
          professional_references: application.professional_references,
          sample_work: application.sample_work,
          sectors: application.sectors,
          functions: application.functions,
          jurisdictions: application.jurisdictions,
        },
        headers: getAccessTokenHeaders(),
      });
      if (res.error) {
        setError(describeGeneratedError(res.error));
      } else {
        onStarted();
      }
    } catch {
      setError("An unexpected error occurred.");
    } finally {
      setStarting(false);
    }
  }

  return (
    <div className="flex flex-col gap-4 rounded-xl border border-border-default bg-surface-1 p-5 shadow-sm sm:flex-row sm:items-center sm:justify-between">
      <p className="max-w-2xl text-sm text-foreground-muted">
        This application was not approved. You can start a new one — your previous
        answers are carried over so you can revise them before resubmitting.
        {error ? <span className="mt-2 block text-error">{error}</span> : null}
      </p>
      <Button
        className="w-full sm:w-auto"
        disabled={starting}
        loading={starting}
        onClick={handleStart}
      >
        Start a new application
      </Button>
    </div>
  );
}
