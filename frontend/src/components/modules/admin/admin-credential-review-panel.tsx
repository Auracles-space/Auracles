"use client";

/**
 * Admin credential review queue panel.
 *
 * Lets administrators filter submitted Credentials by verification status,
 * inspect submitted evidence via short-lived presigned download URLs, and
 * verify or reject each Credential. Uses only generated OpenAPI client
 * functions and the shared browser-auth helpers.
 *
 * Maps to: FR-ATT credential verification lifecycle (admin review).
 */
import { useEffect, useState } from "react";

import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import { CredentialStatusBadge } from "@/components/modules/attestation/credential-status-badge";
import { TableSkeleton } from "@/components/ui/skeletons/table-skeleton";
import { Button } from "@/components/ui/button";
import {
  downloadCredentialEvidenceV1AdminCredentialsCredentialIdEvidenceGet,
  listCredentialReviewQueueV1AdminCredentialsGet,
  rejectCredentialV1AdminCredentialsCredentialIdRejectPost,
  verifyCredentialV1AdminCredentialsCredentialIdVerifyPost,
} from "@/lib/generated/sdk.gen";
import type { AdminCredentialResponse } from "@/lib/generated/types.gen";

/** Selectable review-queue status filters. */
type StatusFilter = "pending" | "verified" | "rejected" | "unverified";

/** Ordered filter tabs rendered above the queue. */
const STATUS_FILTERS: { label: string; value: StatusFilter }[] = [
  { label: "Pending", value: "pending" },
  { label: "Verified", value: "verified" },
  { label: "Rejected", value: "rejected" },
  { label: "Unverified", value: "unverified" },
];

/**
 * Whether a Credential's expiry date has passed relative to now.
 *
 * @param expiresDate - ISO expiry date or null when the credential never lapses.
 */
function isExpired(expiresDate: string | null): boolean {
  if (!expiresDate) {
    return false;
  }
  return new Date(expiresDate).getTime() < Date.now();
}

/**
 * Reduce an S3 object key to its last path segment for display.
 *
 * @param key - Full evidence object key.
 */
function evidenceFileName(key: string): string {
  const segments = key.split("/");
  return segments[segments.length - 1] || key;
}

/**
 * Render a user-facing error box, or nothing when there is no error.
 *
 * @param message - Error copy to display, or null.
 */
function ErrorMessage({ message }: { message: string | null }) {
  if (!message) {
    return null;
  }
  return (
    <p className="rounded-xl border border-error/30 bg-error/10 p-4 text-sm text-error">
      {message}
    </p>
  );
}

/**
 * Render the admin credential review queue with filtering and review actions.
 */
export function AdminCredentialReviewPanel() {
  const [credentials, setCredentials] = useState<AdminCredentialResponse[]>([]);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("pending");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [rejectOpenId, setRejectOpenId] = useState<string | null>(null);
  const [rejectReason, setRejectReason] = useState("");
  const [downloadBusyKey, setDownloadBusyKey] = useState<string | null>(null);

  useEffect(() => {
    void loadQueue(statusFilter);
    // Reload whenever the active status filter changes.
  }, [statusFilter]);

  /**
   * Load the credential review queue for one status filter.
   *
   * @param status - Verification status to query.
   */
  async function loadQueue(status: StatusFilter) {
    setLoading(true);
    setError(null);
    configureBrowserClient();
    const result = await listCredentialReviewQueueV1AdminCredentialsGet({
      headers: getAccessTokenHeaders(),
      query: { status },
    });
    if (!result.response.ok || !result.data) {
      setError(describeGeneratedError(result.error));
      setLoading(false);
      return;
    }
    setCredentials(result.data.credentials);
    setLoading(false);
  }

  /**
   * Replace one row in local state from a fresh server response.
   *
   * @param updated - Updated credential returned by a review action.
   */
  function applyUpdate(updated: AdminCredentialResponse) {
    setCredentials((current) =>
      current.map((item) => (item.id === updated.id ? updated : item)),
    );
  }

  /**
   * Verify one Credential and refresh its row from the response.
   *
   * @param credentialId - Credential UUID to verify.
   */
  async function handleVerify(credentialId: string) {
    setError(null);
    setBusyId(credentialId);
    configureBrowserClient();
    const result = await verifyCredentialV1AdminCredentialsCredentialIdVerifyPost({
      headers: getAccessTokenHeaders(),
      path: { credential_id: credentialId },
    });
    setBusyId(null);
    if (!result.response.ok || !result.data) {
      setError(describeGeneratedError(result.error));
      return;
    }
    applyUpdate(result.data);
  }

  /**
   * Reject one Credential with a required reason and refresh its row.
   *
   * @param credentialId - Credential UUID to reject.
   */
  async function handleReject(credentialId: string) {
    if (!rejectReason.trim()) {
      setError("A rejection reason is required.");
      return;
    }
    setError(null);
    setBusyId(credentialId);
    configureBrowserClient();
    const result = await rejectCredentialV1AdminCredentialsCredentialIdRejectPost({
      body: { reason: rejectReason.trim() },
      headers: getAccessTokenHeaders(),
      path: { credential_id: credentialId },
    });
    setBusyId(null);
    if (!result.response.ok || !result.data) {
      setError(describeGeneratedError(result.error));
      return;
    }
    setRejectOpenId(null);
    setRejectReason("");
    applyUpdate(result.data);
  }

  /**
   * Fetch a presigned evidence URL and open it in a new tab.
   *
   * @param credentialId - Owning Credential UUID.
   * @param key - Evidence object key to download.
   */
  async function handleViewEvidence(credentialId: string, key: string) {
    setError(null);
    setDownloadBusyKey(`${credentialId}:${key}`);
    configureBrowserClient();
    const result =
      await downloadCredentialEvidenceV1AdminCredentialsCredentialIdEvidenceGet({
        headers: getAccessTokenHeaders(),
        path: { credential_id: credentialId },
        query: { key },
      });
    setDownloadBusyKey(null);
    if (!result.response.ok || !result.data) {
      setError(describeGeneratedError(result.error));
      return;
    }
    window.open(result.data.url, "_blank", "noopener,noreferrer");
  }

  return (
    <section className="grid gap-6">
      <div className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
        <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
          Admin credentials
        </p>
        <h1 className="mt-2 font-heading text-3xl font-bold text-foreground">
          Credential review queue
        </h1>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-foreground-muted">
          Review submitted professional credentials, inspect supporting
          evidence, and verify or reject each submission.
        </p>
      </div>

      <ErrorMessage message={error} />

      <nav
        aria-label="Filter credentials by status"
        className="flex flex-wrap gap-1 rounded-2xl border border-border-default bg-surface-1 p-1.5 shadow-sm max-w-lg"
      >
        {STATUS_FILTERS.map((filter) => {
          const isActive = filter.value === statusFilter;
          return (
            <button
              aria-pressed={isActive}
              className={[
                "flex-1 min-h-11 rounded-xl px-4 text-sm font-semibold transition-all outline-none focus-visible:ring-2 focus-visible:ring-accent",
                isActive
                  ? "bg-foreground text-background shadow-sm"
                  : "text-foreground-muted hover:bg-surface-2 hover:text-foreground",
              ].join(" ")}
              key={filter.value}
              onClick={() => setStatusFilter(filter.value)}
              type="button"
            >
              {filter.label}
            </button>
          );
        })}
      </nav>

      {loading ? (
        <TableSkeleton />
      ) : credentials.length === 0 ? (
        <p className="rounded-2xl border border-border-default bg-surface-1 p-6 text-sm text-foreground-muted">
          No credentials in this status.
        </p>
      ) : (
        <div className="grid gap-4">
          {credentials.map((credential) => {
            const isPending = credential.verification_status === "pending";
            const isBusy = busyId === credential.id;
            return (
              <article
                className="rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm"
                key={credential.id}
              >
                <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border-default/45 pb-4">
                  <div className="min-w-0">
                    <h2 className="font-heading text-lg font-bold text-foreground">
                      {credential.title}
                    </h2>
                    <p className="mt-1 break-words text-xs font-mono text-foreground-muted">
                      Owner {credential.user_id}
                    </p>
                  </div>
                  <CredentialStatusBadge
                    expired={isExpired(credential.expires_date)}
                    status={credential.verification_status}
                  />
                </div>

                <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-2">
                  <div>
                    <dt className="text-xs font-semibold uppercase tracking-[0.05em] text-foreground-muted">
                      Issuer
                    </dt>
                    <dd className="mt-1 break-words text-foreground">
                      {credential.issuer}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs font-semibold uppercase tracking-[0.05em] text-foreground-muted">
                      Credential type
                    </dt>
                    <dd className="mt-1 text-foreground">
                      {credential.credential_type ?? "—"}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs font-semibold uppercase tracking-[0.05em] text-foreground-muted">
                      Issuer type
                    </dt>
                    <dd className="mt-1 text-foreground">
                      {credential.issuer_type ?? "—"}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs font-semibold uppercase tracking-[0.05em] text-foreground-muted">
                      Reference number
                    </dt>
                    <dd className="mt-1 break-words text-foreground">
                      {credential.reference_number ?? "—"}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs font-semibold uppercase tracking-[0.05em] text-foreground-muted">
                      Verification URL
                    </dt>
                    <dd className="mt-1 break-words text-foreground">
                      {credential.verification_url ? (
                        <a
                          className="text-accent underline outline-none focus-visible:ring-2 focus-visible:ring-accent"
                          href={credential.verification_url}
                          rel="noreferrer noopener"
                          target="_blank"
                        >
                          {credential.verification_url}
                        </a>
                      ) : (
                        "—"
                      )}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs font-semibold uppercase tracking-[0.05em] text-foreground-muted">
                      Submitted at
                    </dt>
                    <dd className="mt-1 text-foreground">
                      {credential.submitted_at ?? "—"}
                    </dd>
                  </div>
                </dl>

                <div className="mt-4 border-t border-border-default/45 pt-4">
                  <p className="text-xs font-semibold uppercase tracking-[0.05em] text-foreground-muted">
                    Evidence
                  </p>
                  {credential.evidence_file_keys.length === 0 ? (
                    <p className="mt-2 text-sm text-foreground-muted">
                      No evidence attached.
                    </p>
                  ) : (
                    <ul className="mt-2 grid gap-2">
                      {credential.evidence_file_keys.map((key) => (
                        <li
                          className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border-default bg-surface-2 px-3 py-2"
                          key={key}
                        >
                          <span className="min-w-0 break-words text-sm text-foreground font-medium">
                            {evidenceFileName(key)}
                          </span>
                          <Button
                            disabled={
                              downloadBusyKey === `${credential.id}:${key}`
                            }
                            onClick={() =>
                              handleViewEvidence(credential.id, key)
                            }
                            size="sm"
                            variant="secondary"
                          >
                            View
                          </Button>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>

                {credential.rejection_reason ? (
                  <p className="mt-4 rounded-xl border border-error/30 bg-error/10 p-3 text-sm text-error font-medium">
                    Rejection reason: {credential.rejection_reason}
                  </p>
                ) : null}

                {isPending ? (
                  <div className="mt-4 border-t border-border-default/45 pt-4 grid gap-3">
                    <div className="flex flex-wrap gap-3">
                      <Button
                        disabled={isBusy}
                        onClick={() => handleVerify(credential.id)}
                      >
                        Verify
                      </Button>
                      <Button
                        disabled={isBusy}
                        onClick={() => {
                          setRejectReason("");
                          setRejectOpenId(
                            rejectOpenId === credential.id
                              ? null
                              : credential.id,
                          );
                        }}
                        variant="destructive"
                      >
                        Reject
                      </Button>
                    </div>
                    {rejectOpenId === credential.id ? (
                      <div className="grid gap-3 rounded-xl bg-surface-2 p-4 border border-border-default">
                        <label className="grid gap-2 text-sm font-semibold text-foreground">
                          Rejection reason
                          <textarea
                            className="min-h-24 rounded-xl border border-border-default bg-background px-3 py-2 text-sm text-foreground outline-none transition-all focus-visible:ring-2 focus-visible:ring-accent"
                            onChange={(event) =>
                              setRejectReason(event.target.value)
                            }
                            value={rejectReason}
                          />
                        </label>
                        <Button
                          disabled={isBusy || !rejectReason.trim()}
                          onClick={() => handleReject(credential.id)}
                          variant="destructive"
                        >
                          Confirm reject
                        </Button>
                      </div>
                    ) : null}
                  </div>
                ) : null}
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
}
