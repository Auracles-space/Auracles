"use client";

/**
 * Admin attestation queue.
 *
 * Needs-admin requests (auto-matching found no attestor) are assigned or
 * refunded inline; every other status is a read-only browse with a detail
 * modal. Attestor applications live on the Attestors page.
 */
import { useEffect, useState } from "react";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import { Select } from "@/components/ui/select";
import { listAdminAttestations, listAttestorOrgs } from "@/lib/generated/sdk.gen";
import type {
  AttestationRequestResponse,
  AttestorDirectoryEntry,
} from "@/lib/generated/types.gen";
import { ErrorMessage, HeaderCard } from "@/components/modules/attestation/attestation-status";
import { StatusPill } from "@/components/ui/status-pill";
import { NeedsAdminRow } from "@/components/modules/admin/needs-admin-row";
import { emitNeedsAdminChanged } from "@/components/modules/admin/admin-events";
import { AttestationDetailModal } from "@/components/modules/admin/attestation-detail-modal";

/**
 * Render the needs-admin queue and the read-only status browser.
 */
export function AdminAttestationPanel() {
  const [queueItems, setQueueItems] = useState<AttestationRequestResponse[]>([]);
  const [queueStatus, setQueueStatus] = useState("needs_admin");
  const [attestorOrgs, setAttestorOrgs] = useState<AttestorDirectoryEntry[]>([]);
  const [detailId, setDetailId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void loadAttestorOrgs();
  }, []);

  useEffect(() => {
    void loadQueue(queueStatus);
  }, [queueStatus]);

  /** Load active attestor orgs for the manual-assign org picker. */
  async function loadAttestorOrgs() {
    configureBrowserClient();
    const result = await listAttestorOrgs({ headers: getAccessTokenHeaders() });
    if (result.response.ok && result.data) {
      setAttestorOrgs(result.data.attestors);
    }
  }

  /** Load attestations in the given status for the admin queue/history. */
  async function loadQueue(status: string) {
    configureBrowserClient();
    const result = await listAdminAttestations({
      headers: getAccessTokenHeaders(),
      query: { status },
    });
    if (!result.response.ok || !result.data) {
      setError(describeGeneratedError(result.error));
      return;
    }
    setQueueItems(result.data.attestations);
  }

  /** Drop a request from the queue once it is assigned or refunded. */
  function handleNeedsAdminResolved(attestationId: string) {
    setQueueItems((current) =>
      current.filter((item) => item.id !== attestationId),
    );
    // Let the workspace shell refresh its needs-admin count badge.
    emitNeedsAdminChanged();
  }

  return (
    <section className="grid gap-6">
      <HeaderCard
        eyebrow="Trust"
        title="Attestations"
        summary="Assign requests that auto-matching could not staff, refund the ones that cannot proceed, and browse every attestation by status. Applications live under Attestors; disputes under Disputes."
      />

      <ErrorMessage message={error} />

      <div className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h3 className="font-heading text-lg font-bold text-foreground">
            Attestations
            {queueStatus === "needs_admin" && queueItems.length > 0
              ? ` (${queueItems.length})`
              : ""}
          </h3>
          <label className="grid gap-1.5 text-xs font-semibold uppercase tracking-wider text-foreground-muted">
            Status
            <Select
              onChange={(event) => setQueueStatus(event.target.value)}
              value={queueStatus}
            >
              <option value="needs_admin">Needs admin</option>
              <option value="offered">Offered (assigned)</option>
              <option value="accepted">Accepted</option>
              <option value="in_review">In review</option>
              <option value="report_submitted">Report submitted</option>
              <option value="closed">Closed / refunded</option>
            </Select>
          </label>
        </div>
        <p className="mt-1 text-sm text-foreground-muted">
          {queueStatus === "needs_admin"
            ? "Requests auto-matching could not staff. Assign each to an attestor org (the org then staffs its own reviewer) or refund the fee — inline."
            : "Read-only view of attestations in this status."}
        </p>
        <div className="mt-4 grid gap-3">
          {queueItems.length === 0 ? (
            <p className="text-sm text-foreground-muted">
              No attestations in this status.
            </p>
          ) : queueStatus === "needs_admin" ? (
            queueItems.map((item) => (
              <NeedsAdminRow
                attestation={item}
                attestorOrgs={attestorOrgs}
                key={item.id}
                onResolved={handleNeedsAdminResolved}
              />
            ))
          ) : (
            queueItems.map((item) => (
              <button
                className="grid gap-2 rounded-xl border border-border-default bg-surface-1 p-4 text-left shadow-sm outline-none transition-colors hover:border-border-strong hover:bg-surface-2 focus-visible:ring-2 focus-visible:ring-accent sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center"
                key={item.id}
                onClick={() => setDetailId(item.id)}
                type="button"
              >
                <div>
                  <p className="font-heading text-sm font-bold text-foreground">
                    {item.review_type
                      ? `${item.review_type} review`
                      : "Attestation request"}
                  </p>
                  <p className="mt-1 text-xs text-foreground-muted">
                    {item.id} · {item.currency} {item.fee_amount}
                  </p>
                </div>
                <StatusPill status={item.status} />
              </button>
            ))
          )}
        </div>
      </div>

      {detailId ? (
        <AttestationDetailModal
          attestationId={detailId}
          onClose={() => setDetailId(null)}
        />
      ) : null}
    </section>
  );
}
