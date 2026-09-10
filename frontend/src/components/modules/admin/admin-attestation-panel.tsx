"use client";

import { useEffect, useState } from "react";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import { Select } from "@/components/ui/select";
import {
  listAdminAttestations,
  listAttestorOrgs,
  listOrgAttestorApplicationsForAdmin,
} from "@/lib/generated/sdk.gen";
import type {
  AttestationRequestResponse,
  AttestorDirectoryEntry,
  OrgAttestorApplicationResponse,
} from "@/lib/generated/types.gen";
import {
  ErrorMessage,
  HeaderCard,
  StatusTag,
} from "@/components/modules/attestation/attestation-status";
import { NeedsAdminRow } from "@/components/modules/admin/needs-admin-row";
import { AttestorApplicationRow } from "@/components/modules/admin/attestor-application-row";
import { emitNeedsAdminChanged } from "@/components/modules/admin/admin-events";
import { AttestationDetailModal } from "@/components/modules/admin/attestation-detail-modal";

export function AdminAttestationPanel() {
  const [applications, setApplications] = useState<OrgAttestorApplicationResponse[]>([]);
  const [queueItems, setQueueItems] = useState<AttestationRequestResponse[]>([]);
  const [queueStatus, setQueueStatus] = useState("needs_admin");
  const [attestorOrgs, setAttestorOrgs] = useState<AttestorDirectoryEntry[]>([]);
  const [detailId, setDetailId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void loadApplications();
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

  async function loadApplications() {
    configureBrowserClient();
    const result = await listOrgAttestorApplicationsForAdmin({
      headers: getAccessTokenHeaders(),
      query: { status: "submitted" },
    });
    if (!result.response.ok || !result.data) {
      setError(describeGeneratedError(result.error));
      return;
    }
    setApplications(result.data.applications);
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

  /** Drop an application from the list once it is rejected. */
  function handleApplicationRejected(applicationId: string) {
    setApplications((current) =>
      current.filter((item) => item.id !== applicationId),
    );
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
        eyebrow="Admin attestation"
        title="Review and resolution"
        summary="Review Attestor applications, manually assign exhausted requests, and refund needs-admin requests. Disputes resolve under Admin → Disputes."
      />
      
      <ErrorMessage message={error} />

      <div className="grid gap-3">
        {applications.length === 0 ? (
          <p className="rounded-2xl border border-border-default bg-surface-1 p-6 text-sm text-foreground-muted">
            No applications to show.
          </p>
        ) : (
          applications.map((application) => (
            <AttestorApplicationRow
              application={application}
              key={application.id}
              onRejected={handleApplicationRejected}
            />
          ))
        )}
      </div>

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
                <StatusTag value={item.status} />
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
