"use client";

/**
 * Pending business-verification (KYB) queue for platform admins.
 *
 * Every organization is verified before it can activate a capability, so this
 * queue is the gate for org onboarding: an org waits here until an admin reads
 * its incorporation documents and records a verdict.
 *
 * Verifying unlocks everything an organization can do, so the decision is a
 * sensitive action: the API requires a step-up 2FA window, which the global
 * step-up prompt handles when the call is refused. Rejection is not terminal —
 * the org fixes what the notes say and submits again — so a rejection must
 * carry a reason. Notes are keyed per org so each row decides on its own.
 *
 * Maps to: DESIGN-1.
 */
import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { StatusPill, ownerStatusKey } from "@/components/ui/status-pill";
import { Textarea } from "@/components/ui/textarea";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import { adminListOrgsV1AdminOrgsGet, adminReviewOrgKyb } from "@/lib/generated/sdk.gen";
import { AdminOrgKybDocuments } from "@/components/modules/admin/admin-org-kyb-documents";
import { emitOrgVerificationChanged } from "@/components/modules/admin/admin-events";
import type { AdminOrgResponse } from "@/lib/generated/types.gen";

/**
 * Render the queue of organizations awaiting a verification decision.
 */
export function AdminOrgVerificationQueue() {
  const [orgs, setOrgs] = useState<AdminOrgResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [notes, setNotes] = useState<Record<string, string>>({});

  const load = useCallback(async () => {
    configureBrowserClient();
    const result = await adminListOrgsV1AdminOrgsGet({
      headers: getAccessTokenHeaders(),
      query: { kyb_status: "pending", page: 1, page_size: 50 },
    });
    setLoading(false);
    if (!result.response.ok || !result.data) {
      setError(describeGeneratedError(result.error));
      return;
    }
    setOrgs(result.data.orgs);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  /**
   * Record one verdict.
   *
   * @param orgId - Organization being decided.
   * @param verdict - `verified` or `rejected`.
   */
  async function decide(orgId: string, verdict: "verified" | "rejected") {
    setBusyId(orgId);
    setError(null);
    setNotice(null);
    const result = await adminReviewOrgKyb({
      body: {
        notes: notes[orgId]?.trim() || null,
        verdict,
      },
      headers: getAccessTokenHeaders(),
      path: { org_id: orgId },
    });
    setBusyId(null);
    if (!result.response.ok) {
      setError(describeGeneratedError(result.error));
      return;
    }
    setNotice(
      verdict === "verified"
        ? "Organization verified. Its capabilities can now be activated."
        : "Organization returned for changes.",
    );
    // Keep the Organizations badge in the admin nav in step with the queue.
    emitOrgVerificationChanged();
    await load();
  }

  if (loading) {
    return (
      <div className="flex min-h-64 items-center justify-center">
        <Spinner className="h-8 w-8 text-accent" />
      </div>
    );
  }

  return (
    <section className="grid gap-4">
      <div className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
        <h2 className="font-heading text-xl font-bold text-foreground">
          Pending verification
          {orgs.length > 0 ? ` (${orgs.length})` : ""}
        </h2>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-foreground-muted">
          These organizations cannot activate any capability until they are
          verified. Open each document, check it against the registered name and
          number, then record a decision.
        </p>
      </div>

      {error ? (
        <p className="rounded-xl border border-error/30 bg-error/10 p-4 text-sm text-error">
          {error}
        </p>
      ) : null}
      {notice ? (
        <p className="rounded-xl border border-success/30 bg-success/10 p-4 text-sm text-success">
          {notice}
        </p>
      ) : null}

      {orgs.length === 0 ? (
        <p className="rounded-2xl border border-border-default bg-surface-1 p-6 text-sm text-foreground-muted shadow-sm">
          No organizations are waiting for verification.
        </p>
      ) : null}

      {orgs.map((org) => (
        <article
          className="rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm"
          key={org.id}
        >
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h3 className="font-heading text-lg font-bold text-foreground">
                {org.legal_name || org.name}
              </h3>
              <p className="mt-1 text-sm text-foreground-muted">
                {org.name} · {org.country} ·{" "}
                {org.registration_number || "No registration number"}
              </p>
            </div>
            <StatusPill status={ownerStatusKey("pending", "kyb")} />
          </div>

          <div className="mt-4 grid gap-3 rounded-xl border border-border-default bg-surface-2 p-4">
            <AdminOrgKybDocuments orgId={org.id} />
            <label className="grid gap-2 text-sm font-semibold text-foreground">
              Notes to the organization
              <Textarea
                onChange={(event) =>
                  setNotes((current) => ({
                    ...current,
                    [org.id]: event.target.value,
                  }))
                }
                placeholder="Required when returning it for changes — say what to fix."
                value={notes[org.id] ?? ""}
              />
            </label>
            <div className="flex flex-col gap-3 sm:flex-row">
              <Button
                disabled={busyId === org.id}
                loading={busyId === org.id}
                onClick={() => decide(org.id, "verified")}
              >
                Verify organization
              </Button>
              <button
                className="min-h-12 rounded-xl border border-error/50 px-6 text-sm font-semibold text-error outline-none transition-colors hover:bg-error/10 focus-visible:ring-2 focus-visible:ring-error disabled:cursor-not-allowed disabled:opacity-60"
                disabled={busyId === org.id || !(notes[org.id] ?? "").trim()}
                onClick={() => decide(org.id, "rejected")}
                type="button"
              >
                Return for changes
              </button>
            </div>
          </div>
        </article>
      ))}
    </section>
  );
}
