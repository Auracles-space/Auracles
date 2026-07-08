"use client";

import { useEffect, useState } from "react";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import { Button } from "@/components/ui/button";
import { TableSkeleton } from "@/components/ui/skeletons/table-skeleton";
import {
  listOrgAttestorApplicationsForAdmin,
  verifyOrgAttestorKyb,
  orgAttestorNeedsInfo,
  startOrgAttestorTrial,
  approveOrgAttestor,
  rejectOrgAttestor,
  suspendOrgAttestorCapability,
  reinstateOrgAttestorCapability,
  revokeOrgAttestorCapability,
} from "@/lib/generated/sdk.gen";
import type { OrgAttestorAdminListItem } from "@/lib/generated/types.gen";

type StatusFilter = "submitted" | "needs_info" | "trial" | "approved" | "rejected";

const STATUS_FILTERS: { label: string; value: StatusFilter }[] = [
  { label: "Submitted", value: "submitted" },
  { label: "Needs Info", value: "needs_info" },
  { label: "Trial", value: "trial" },
  { label: "Approved", value: "approved" },
  { label: "Rejected", value: "rejected" },
];

function ErrorMessage({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <p className="rounded-xl border border-error/30 bg-error/10 p-4 text-sm text-error">
      {message}
    </p>
  );
}

export function AdminOrgAttestorReviewPanel() {
  const [applications, setApplications] = useState<OrgAttestorAdminListItem[]>([]);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("submitted");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const [openFeedbackId, setOpenFeedbackId] = useState<string | null>(null);
  const [feedbackAction, setFeedbackAction] = useState<"needs_info" | "reject" | null>(null);
  const [feedbackText, setFeedbackText] = useState("");

  const [openCapabilityId, setOpenCapabilityId] = useState<string | null>(null);
  const [capabilityAction, setCapabilityAction] = useState<"suspend" | "reinstate" | "revoke" | null>(null);

  useEffect(() => {
    void loadQueue(statusFilter);
  }, [statusFilter]);

  async function loadQueue(status: StatusFilter) {
    setLoading(true);
    setError(null);
    configureBrowserClient();
    try {
      const result = await listOrgAttestorApplicationsForAdmin({
        headers: getAccessTokenHeaders(),
        query: { status },
      });
      if (!result.response.ok || !result.data) {
        setError(describeGeneratedError(result.error));
        setLoading(false);
        return;
      }
      setApplications(result.data.applications);
    } catch {
      setError("Failed to load review queue.");
    } finally {
      setLoading(false);
    }
  }

  function applyUpdate(updatedAppId: string, newStatus: string) {
    setApplications((current) =>
      current.map((item) => (item.id === updatedAppId ? { ...item, status: newStatus } : item))
    );
  }

  async function handleAction(applicationId: string, actionName: string) {
    setError(null);
    setBusyId(applicationId);
    configureBrowserClient();
    
    try {
      let result;
      if (actionName === "verify_kyb") {
        result = await verifyOrgAttestorKyb({
          headers: getAccessTokenHeaders(),
          path: { application_id: applicationId },
        });
      } else if (actionName === "start_trial") {
        result = await startOrgAttestorTrial({
          headers: getAccessTokenHeaders(),
          path: { application_id: applicationId },
        });
      } else if (actionName === "approve") {
        result = await approveOrgAttestor({
          headers: getAccessTokenHeaders(),
          path: { application_id: applicationId },
        });
      }

      if (result && !result.response.ok) {
        setError(describeGeneratedError(result.error));
      } else if (result?.data) {
        applyUpdate(applicationId, (result.data as { status?: string }).status || "updated");
      }
    } catch {
      setError(`Failed to perform action: ${actionName}`);
    } finally {
      setBusyId(null);
    }
  }

  async function handleFeedbackAction(applicationId: string) {
    if (!feedbackText.trim()) {
      setError("Feedback is required.");
      return;
    }
    setError(null);
    setBusyId(applicationId);
    configureBrowserClient();

    try {
      let result;
      if (feedbackAction === "needs_info") {
        result = await orgAttestorNeedsInfo({
          headers: getAccessTokenHeaders(),
          path: { application_id: applicationId },
          body: { feedback: feedbackText },
        });
      } else if (feedbackAction === "reject") {
        result = await rejectOrgAttestor({
          headers: getAccessTokenHeaders(),
          path: { application_id: applicationId },
          body: { feedback: feedbackText },
        });
      }

      if (result && !result.response.ok) {
        setError(describeGeneratedError(result.error));
      } else if (result?.data) {
        applyUpdate(applicationId, (result.data as { status?: string }).status || "updated");
        setOpenFeedbackId(null);
        setFeedbackText("");
        setFeedbackAction(null);
      }
    } catch {
      setError(`Failed to process feedback action.`);
    } finally {
      setBusyId(null);
    }
  }

  async function handleCapabilityAction(orgId: string) {
    setError(null);
    setBusyId(orgId);
    configureBrowserClient();

    try {
      let result;
      if (capabilityAction === "suspend") {
        result = await suspendOrgAttestorCapability({
          headers: getAccessTokenHeaders(),
          path: { org_id: orgId },
        });
      } else if (capabilityAction === "reinstate") {
        result = await reinstateOrgAttestorCapability({
          headers: getAccessTokenHeaders(),
          path: { org_id: orgId },
        });
      } else if (capabilityAction === "revoke") {
        result = await revokeOrgAttestorCapability({
          headers: getAccessTokenHeaders(),
          path: { org_id: orgId },
        });
      }

      if (result && !result.response.ok) {
        setError(describeGeneratedError(result.error));
      } else {
        setOpenCapabilityId(null);
        setCapabilityAction(null);
      }
    } catch {
      setError(`Failed to update capability.`);
    } finally {
      setBusyId(null);
    }
  }

  return (
    <section className="grid gap-6">
      <div className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
        <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
          Admin Org Attestors
        </p>
        <h1 className="mt-2 font-heading text-3xl font-bold text-foreground">
          Attestor Review Queue
        </h1>
      </div>

      <ErrorMessage message={error} />

      <nav
        aria-label="Filter applications by status"
        className="flex flex-wrap gap-1 rounded-2xl border border-border-default bg-surface-1 p-1.5 shadow-sm max-w-2xl"
      >
        {STATUS_FILTERS.map((filter) => {
          const isActive = filter.value === statusFilter;
          return (
            <button
              key={filter.value}
              aria-pressed={isActive}
              className={[
                "flex-1 min-h-11 rounded-xl px-4 text-sm font-semibold transition-all outline-none",
                isActive
                  ? "bg-foreground text-background shadow-sm"
                  : "text-foreground-muted hover:bg-surface-2 hover:text-foreground",
              ].join(" ")}
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
      ) : applications.length === 0 ? (
        <p className="rounded-2xl border border-border-default bg-surface-1 p-6 text-sm text-foreground-muted">
          No applications in this status.
        </p>
      ) : (
        <div className="grid gap-4">
          {applications.map((app) => {
            const isBusy = busyId === app.id || busyId === app.org_id;

            return (
              <article
                className="rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm"
                key={app.id}
              >
                <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border-default/45 pb-4">
                  <div className="min-w-0">
                    <h2 className="font-heading text-lg font-bold text-foreground">
                      {app.legal_name || "Unknown Org"}
                    </h2>
                    <p className="mt-1 break-words text-xs font-mono text-foreground-muted">
                      App ID: {app.id} | Org ID: {app.org_id}
                    </p>
                  </div>
                  <span className="px-3 py-1 bg-surface-2 border border-border-strong rounded-full text-xs font-medium uppercase tracking-wider">
                    {app.status}
                  </span>
                </div>

                <div className="mt-4 text-sm space-y-2">
                  <p><span className="font-semibold">KYB Verified:</span> {app.kyb_verified_at ? new Date(app.kyb_verified_at).toLocaleString() : "Pending"}</p>
                  <p><span className="font-semibold">Created:</span> {new Date(app.created_at).toLocaleString()}</p>
                  <Button 
                    variant="secondary"
                    className="mt-2"
                    onClick={() => {
                      alert("Contract Gap: The OpenAPI spec does not define an endpoint to download KYB/tax documents for org attestor applications. Stop and Escalate.");
                    }}
                  >
                    View KYB / Tax Documents
                  </Button>
                </div>

                <div className="mt-6 border-t border-border-default/45 pt-4">
                  <h3 className="text-sm font-semibold uppercase tracking-wider text-foreground-muted mb-3">Application Actions</h3>
                  <div className="flex flex-wrap gap-2">
                    <Button
                      disabled={isBusy || app.status !== "submitted"}
                      onClick={() => handleAction(app.id, "verify_kyb")}
                    >
                      Verify KYB
                    </Button>
                    <Button
                      disabled={isBusy}
                      onClick={() => handleAction(app.id, "start_trial")}
                    >
                      Start Trial
                    </Button>
                    <Button
                      disabled={isBusy}
                      onClick={() => handleAction(app.id, "approve")}
                    >
                      Approve
                    </Button>
                    <Button
                      variant="secondary"
                      disabled={isBusy}
                      onClick={() => {
                        setFeedbackAction("needs_info");
                        setOpenFeedbackId(openFeedbackId === app.id ? null : app.id);
                        setFeedbackText("");
                      }}
                    >
                      Needs Info
                    </Button>
                    <Button
                      variant="destructive"
                      disabled={isBusy}
                      onClick={() => {
                        setFeedbackAction("reject");
                        setOpenFeedbackId(openFeedbackId === app.id ? null : app.id);
                        setFeedbackText("");
                      }}
                    >
                      Reject
                    </Button>
                  </div>

                  {openFeedbackId === app.id && feedbackAction && (
                    <div className="mt-4 grid gap-3 rounded-xl bg-surface-2 p-4 border border-border-default">
                      <label className="grid gap-2 text-sm font-semibold text-foreground">
                        {feedbackAction === "reject" ? "Rejection Reason" : "Info Needed"}
                        <textarea
                          className="min-h-24 rounded-xl border border-border-default bg-background px-3 py-2 text-sm text-foreground outline-none transition-all focus-visible:ring-2 focus-visible:ring-accent"
                          onChange={(e) => setFeedbackText(e.target.value)}
                          value={feedbackText}
                        />
                      </label>
                      <Button
                        disabled={isBusy || !feedbackText.trim()}
                        onClick={() => handleFeedbackAction(app.id)}
                        variant={feedbackAction === "reject" ? "destructive" : "primary"}
                      >
                        Confirm {feedbackAction === "reject" ? "Reject" : "Needs Info"}
                      </Button>
                    </div>
                  )}
                </div>

                {app.status === "approved" && (
                  <div className="mt-6 border-t border-border-default/45 pt-4">
                    <h3 className="text-sm font-semibold uppercase tracking-wider text-error mb-3">Capability Controls</h3>
                    <div className="flex flex-wrap gap-2">
                      <Button
                        variant="destructive"
                        disabled={isBusy}
                        onClick={() => {
                          setCapabilityAction("suspend");
                          setOpenCapabilityId(openCapabilityId === app.org_id ? null : app.org_id);
                        }}
                      >
                        Suspend
                      </Button>
                      <Button
                        variant="secondary"
                        disabled={isBusy}
                        onClick={() => {
                          setCapabilityAction("reinstate");
                          setOpenCapabilityId(openCapabilityId === app.org_id ? null : app.org_id);
                        }}
                      >
                        Reinstate
                      </Button>
                      <Button
                        variant="destructive"
                        disabled={isBusy}
                        onClick={() => {
                          setCapabilityAction("revoke");
                          setOpenCapabilityId(openCapabilityId === app.org_id ? null : app.org_id);
                        }}
                      >
                        Revoke
                      </Button>
                    </div>

                    {openCapabilityId === app.org_id && capabilityAction && (
                      <div className="mt-4 grid gap-3 rounded-xl border border-error/50 bg-error/5 p-4 text-error">
                        <p className="font-semibold text-sm">
                          Are you sure you want to {capabilityAction} capability for this organization?
                        </p>
                        <Button
                          disabled={isBusy}
                          onClick={() => handleCapabilityAction(app.org_id)}
                          variant="destructive"
                        >
                          Confirm {capabilityAction}
                        </Button>
                      </div>
                    )}
                  </div>
                )}
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
}
