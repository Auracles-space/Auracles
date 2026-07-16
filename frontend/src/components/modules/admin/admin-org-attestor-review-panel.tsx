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
  adminDecideTrialV1AdminOrgAttestorApplicationsApplicationIdTrialDecidePost as adminDecideTrial,
  adminGetTrialGradeV1AdminOrgAttestorApplicationsApplicationIdTrialGet as adminGetTrialGrade,
  adminListCalibrationFixturesV1AdminOrgAttestorApplicationsCalibrationFixturesGet as adminListCalibrationFixtures,
  listOrgAttestorApplicationsForAdmin,
  listOrgAttestorDocumentsForAdmin,
  verifyOrgAttestorKyb,
  orgAttestorNeedsInfo,
  startOrgAttestorTrial,
  approveOrgAttestor,
  rejectOrgAttestor,
  suspendOrgAttestorCapability,
  reinstateOrgAttestorCapability,
  revokeOrgAttestorCapability,
} from "@/lib/generated/sdk.gen";
import type {
  AdminTrialGradeResponse,
  CalibrationFixtureItem,
  OrgAttestorAdminListItem,
  OrgAttestorDocumentLink,
} from "@/lib/generated/types.gen";

type StatusFilter = "submitted" | "needs_info" | "trial" | "approved" | "rejected";

const UNDER_REVIEW: ReadonlySet<string> = new Set(["submitted", "needs_info"]);

const STATUS_FILTERS: { label: string; value: StatusFilter }[] = [
  { label: "Submitted", value: "submitted" },
  { label: "Needs Info", value: "needs_info" },
  { label: "Trial", value: "trial" },
  { label: "Approved", value: "approved" },
  { label: "Rejected", value: "rejected" },
];

// One-click feedback presets for the most common send-back reasons, so an
// admin can unblock an application without retyping the same guidance.
const NEEDS_INFO_PRESETS: { label: string; text: string }[] = [
  {
    label: "Payout account",
    text:
      "Please connect a payout account under the Payout Account step so we can "
      + "release attestation earnings, then resubmit.",
  },
  {
    label: "Tax documents",
    text:
      "Please upload the tax documents required for payouts under the Tax "
      + "Documents step, then resubmit.",
  },
  {
    label: "Calibration trial",
    text:
      "Please nominate a member to complete the calibration trial before "
      + "resubmitting.",
  },
];

function ErrorMessage({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <p className="rounded-xl border border-error/30 bg-error/10 p-4 text-sm text-error">
      {message}
    </p>
  );
}

function NoticeMessage({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <p className="rounded-xl border border-success/30 bg-success/10 p-4 text-sm text-success">
      {message}
    </p>
  );
}

export function AdminOrgAttestorReviewPanel() {
  const [applications, setApplications] = useState<OrgAttestorAdminListItem[]>([]);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("submitted");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const [openFeedbackId, setOpenFeedbackId] = useState<string | null>(null);
  const [feedbackAction, setFeedbackAction] = useState<"needs_info" | "reject" | null>(null);
  const [feedbackText, setFeedbackText] = useState("");

  const [openCapabilityId, setOpenCapabilityId] = useState<string | null>(null);
  const [capabilityAction, setCapabilityAction] = useState<"suspend" | "reinstate" | "revoke" | null>(null);

  const [openDocsId, setOpenDocsId] = useState<string | null>(null);
  const [docsBusyId, setDocsBusyId] = useState<string | null>(null);
  const [docsByApp, setDocsByApp] = useState<Record<string, OrgAttestorDocumentLink[]>>({});
  const [fixtures, setFixtures] = useState<CalibrationFixtureItem[]>([]);
  const [selectedFixtureByApp, setSelectedFixtureByApp] = useState<Record<string, string>>({});
  const [trialGradesByApp, setTrialGradesByApp] = useState<Record<string, AdminTrialGradeResponse>>(
    {},
  );
  const [trialFeedbackByApp, setTrialFeedbackByApp] = useState<Record<string, string>>({});

  useEffect(() => {
    void loadQueue(statusFilter);
  }, [statusFilter]);

  useEffect(() => {
    void loadFixtures();
  }, []);

  useEffect(() => {
    const submittedApps = applications.filter((app) => app.trial_status === "submitted");
    submittedApps.forEach((app) => {
      if (!trialGradesByApp[app.id]) {
        void loadTrialGrade(app.id);
      }
    });
  }, [applications, trialGradesByApp]);

  async function loadQueue(status: StatusFilter) {
    setLoading(true);
    setError(null);
    setNotice(null);
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

  async function loadFixtures() {
    configureBrowserClient();
    try {
      const result = await adminListCalibrationFixtures({
        headers: getAccessTokenHeaders(),
      });
      if (!result.response.ok || !result.data) {
        setError(describeGeneratedError(result.error));
        return;
      }
      setFixtures(result.data.fixtures);
    } catch {
      setError("Failed to load calibration fixtures.");
    }
  }

  async function loadTrialGrade(applicationId: string) {
    configureBrowserClient();
    try {
      const result = await adminGetTrialGrade({
        headers: getAccessTokenHeaders(),
        path: { application_id: applicationId },
      });
      if (!result.response.ok || !result.data) {
        setError(describeGeneratedError(result.error));
        return;
      }
      setTrialGradesByApp((current) => ({ ...current, [applicationId]: result.data }));
    } catch {
      setError("Failed to load trial grade.");
    }
  }

  function applyUpdate(
    updatedAppId: string,
    patch: Partial<OrgAttestorAdminListItem>,
  ) {
    setApplications((current) =>
      current.map((item) => (item.id === updatedAppId ? { ...item, ...patch } : item))
    );
  }

  // Success messages per action. Verify KYB and Start Trial leave the
  // application's status unchanged, so without an explicit confirmation the
  // admin sees no feedback and assumes the click did nothing.
  const ACTION_SUCCESS: Record<string, string> = {
    verify_kyb: "KYB verified.",
    start_trial: "Trial assigned to the nominated member.",
    approve: "Application approved and attestor capability activated.",
  };

  async function handleAction(applicationId: string, actionName: string) {
    setError(null);
    setNotice(null);
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
        const frameworkId = selectedFixtureByApp[applicationId];
        if (!frameworkId) {
          setError("Select a calibration fixture before starting the trial.");
          setBusyId(null);
          return;
        }
        result = await startOrgAttestorTrial({
          headers: getAccessTokenHeaders(),
          path: { application_id: applicationId },
          body: { framework_id: frameworkId },
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
        const data = result.data as {
          status?: string;
          kyb_verified_at?: string | null;
        };
        // Merge every field the row displays, not just status — verify_kyb
        // updates kyb_verified_at while leaving status put. start_trial's
        // response is the application (no trial_status), so reflect the
        // freshly-assigned trial here or the gate never advances and Start
        // Trial re-enables for a re-assign.
        applyUpdate(applicationId, {
          ...(data.status ? { status: data.status } : {}),
          ...(data.kyb_verified_at !== undefined
            ? { kyb_verified_at: data.kyb_verified_at }
            : {}),
          ...(actionName === "start_trial" ? { trial_status: "assigned" } : {}),
          // Approve activates the attestor capability server-side; reflect it
          // here so the Capability Controls enable without a queue refetch.
          ...(actionName === "approve" ? { capability_status: "active" } : {}),
        });
        setNotice(ACTION_SUCCESS[actionName] ?? "Done.");
      }
    } catch {
      setError(`Failed to perform action: ${actionName}`);
    } finally {
      setBusyId(null);
    }
  }

  async function handleTrialDecision(applicationId: string, resultName: "pass" | "fail") {
    setError(null);
    setNotice(null);
    setBusyId(applicationId);
    configureBrowserClient();
    try {
      const result = await adminDecideTrial({
        headers: getAccessTokenHeaders(),
        path: { application_id: applicationId },
        body: {
          result: resultName,
          feedback: trialFeedbackByApp[applicationId] || undefined,
        },
      });
      if (!result.response.ok || !result.data) {
        setError(describeGeneratedError(result.error));
        return;
      }
      applyUpdate(applicationId, {
        status: result.data.status,
        trial_status: resultName === "pass" ? "passed" : "failed",
      });
      setTrialGradesByApp((current) => {
        const next = { ...current };
        delete next[applicationId];
        return next;
      });
      setNotice(
        resultName === "pass" ? "Trial marked as passed." : "Trial marked as failed.",
      );
    } catch {
      setError("Failed to decide the trial.");
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
        const status = (result.data as { status?: string }).status;
        applyUpdate(applicationId, status ? { status } : {});
        setNotice(
          feedbackAction === "reject"
            ? "Application rejected."
            : "Sent back to the org for more information.",
        );
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

  async function handleViewDocuments(applicationId: string) {
    // Toggle closed if already open for this application.
    if (openDocsId === applicationId) {
      setOpenDocsId(null);
      return;
    }
    setOpenDocsId(applicationId);
    setError(null);
    // Fetch fresh links each open: presigned URLs expire after 15 minutes.
    setDocsBusyId(applicationId);
    configureBrowserClient();
    try {
      const result = await listOrgAttestorDocumentsForAdmin({
        headers: getAccessTokenHeaders(),
        path: { application_id: applicationId },
      });
      if (!result.response.ok || !result.data) {
        setError(describeGeneratedError(result.error));
        return;
      }
      setDocsByApp((current) => ({ ...current, [applicationId]: result.data.documents }));
    } catch {
      setError("Failed to load documents.");
    } finally {
      setDocsBusyId(null);
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
      <NoticeMessage message={notice} />

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

            // Gates run in sequence: KYB → trial → approve. Only the next
            // undone step is active; the rest stay disabled until their
            // predecessor completes.
            const underReview = UNDER_REVIEW.has(app.status);
            const kybDone = Boolean(app.kyb_verified_at);
            const trialPassed = app.trial_status === "passed";
            const trialAssigned = app.trial_status === "assigned";
            const trialSubmitted = app.trial_status === "submitted";
            const canVerifyKyb = underReview && !kybDone;
            const canStartTrial =
              underReview && kybDone && !trialPassed && !trialAssigned && !trialSubmitted;
            const canApprove =
              app.status === "submitted" && kybDone && trialPassed;
            const selectedFixtureId = selectedFixtureByApp[app.id] ?? "";
            const grade = trialGradesByApp[app.id];

            const nextStep = !underReview
              ? null
              : !kybDone
                ? "Next: verify KYB."
                : trialAssigned
                  ? "Waiting on the nominee to complete the trial."
                  : trialSubmitted
                    ? "Trial submitted — review the grade below and confirm the outcome."
                  : app.trial_status === "failed"
                    ? "Trial failed — start it again to give the nominee another attempt."
                    : !trialPassed
                      ? "Next: start the calibration trial."
                      : "All gates met — ready to approve.";

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
                  <p><span className="font-semibold">Trial Status:</span> {app.trial_status ?? "not started"}</p>
                  {app.admin_feedback && (
                    <div className="rounded-lg border border-warning/30 bg-warning/10 p-3 text-warning">
                      <span className="mb-1 block font-semibold">Feedback sent to org:</span>
                      {app.admin_feedback}
                    </div>
                  )}
                  <Button
                    variant="secondary"
                    className="mt-2"
                    disabled={docsBusyId === app.id}
                    onClick={() => handleViewDocuments(app.id)}
                  >
                    {openDocsId === app.id ? "Hide" : "View"} KYB / Tax Documents
                  </Button>

                  {openDocsId === app.id && (
                    <div className="mt-3 rounded-xl border border-border-default bg-surface-2 p-4">
                      {docsBusyId === app.id ? (
                        <p className="text-sm text-foreground-muted">Loading documents…</p>
                      ) : (docsByApp[app.id]?.length ?? 0) === 0 ? (
                        <p className="text-sm text-foreground-muted">
                          No documents uploaded for this application.
                        </p>
                      ) : (
                        <ul className="grid gap-2">
                          {docsByApp[app.id].map((doc) =>
                            doc.available === false ? (
                              <li
                                key={`${doc.label}-${doc.filename}`}
                                className="flex min-h-11 items-center gap-2 rounded-lg px-3 text-sm"
                              >
                                <span className="font-semibold text-foreground-muted">
                                  {doc.label}:
                                </span>
                                <span className="break-all text-foreground-muted">
                                  {doc.filename}
                                </span>
                                <span className="rounded bg-warning/10 px-2 py-0.5 text-xs font-semibold text-warning">
                                  Upload incomplete
                                </span>
                              </li>
                            ) : (
                              <li key={doc.url}>
                                <a
                                  className="flex min-h-11 items-center gap-2 rounded-lg px-3 text-sm font-medium text-accent underline-offset-4 hover:underline"
                                  href={doc.url}
                                  rel="noopener noreferrer"
                                  target="_blank"
                                >
                                  <span className="font-semibold">{doc.label}:</span>
                                  <span className="break-all text-foreground">{doc.filename}</span>
                                </a>
                              </li>
                            ),
                          )}
                        </ul>
                      )}
                      <p className="mt-2 text-xs text-foreground-muted">
                        Links expire after 15 minutes.
                      </p>
                    </div>
                  )}
                </div>

                <div className="mt-6 border-t border-border-default/45 pt-4">
                  <h3 className="text-sm font-semibold uppercase tracking-wider text-foreground-muted mb-3">Application Actions</h3>
                  {nextStep && (
                    <p className="mb-3 text-sm text-foreground-muted">{nextStep}</p>
                  )}
                  {canStartTrial ? (
                    <label className="mb-3 grid gap-2 text-sm font-medium text-foreground">
                      <span>Calibration fixture for {app.legal_name || "this organization"}</span>
                      <select
                        aria-label={`Calibration fixture for ${app.legal_name || "this organization"}`}
                        className="min-h-12 rounded-xl border border-border-default bg-background px-4 text-sm text-foreground outline-none transition-colors focus:border-accent"
                        onChange={(event) =>
                          setSelectedFixtureByApp((current) => ({
                            ...current,
                            [app.id]: event.target.value,
                          }))
                        }
                        value={selectedFixtureId}
                      >
                        <option value="">Select a fixture</option>
                        {fixtures.map((fixture) => (
                          <option key={fixture.id} value={fixture.id}>
                            {fixture.title} ({fixture.review_type})
                          </option>
                        ))}
                      </select>
                    </label>
                  ) : null}
                  <div className="flex flex-wrap gap-2">
                    <Button
                      disabled={isBusy || !canVerifyKyb}
                      onClick={() => handleAction(app.id, "verify_kyb")}
                    >
                      Verify KYB
                    </Button>
                    <Button
                      disabled={isBusy || !canStartTrial || !selectedFixtureId}
                      onClick={() => handleAction(app.id, "start_trial")}
                    >
                      Start Trial
                    </Button>
                    <Button
                      disabled={isBusy || !canApprove}
                      onClick={() => handleAction(app.id, "approve")}
                    >
                      Approve
                    </Button>
                    <Button
                      variant="secondary"
                      disabled={isBusy || app.status !== "submitted"}
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
                      disabled={isBusy || app.status === "approved" || app.status === "rejected"}
                      onClick={() => {
                        setFeedbackAction("reject");
                        setOpenFeedbackId(openFeedbackId === app.id ? null : app.id);
                        setFeedbackText("");
                      }}
                    >
                      Reject
                    </Button>
                  </div>

                  {trialSubmitted && grade ? (
                    <div className="mt-4 grid gap-4 rounded-xl border border-border-default bg-surface-2 p-4">
                      <div className="grid gap-2 sm:grid-cols-2">
                        <p className="text-sm text-foreground">
                          <span className="font-semibold">Score:</span>{" "}
                          {grade.score_pct ? `${grade.score_pct}%` : "Pending"}
                        </p>
                        <p className="text-sm text-foreground">
                          <span className="font-semibold">Suggested result:</span>{" "}
                          {grade.auto_result ?? "pending"}
                        </p>
                      </div>

                      <div className="grid gap-3">
                        {grade.rows.map((row) => (
                          <div
                            key={row.dimension_id}
                            className="rounded-xl border border-border-default bg-surface-1 p-4"
                          >
                            <p className="font-semibold text-foreground">{row.label}</p>
                            <p className="mt-1 text-sm text-foreground-muted">
                              Nominee: {row.nominee_score ?? "n/a"} | Key: {row.expected_score} | Tolerance: {row.tolerance}
                            </p>
                            {row.nominee_comment ? (
                              <p className="mt-2 text-sm text-foreground">{row.nominee_comment}</p>
                            ) : null}
                          </div>
                        ))}
                      </div>

                      <label className="grid gap-2 text-sm font-medium text-foreground">
                        Feedback
                        <textarea
                          className="min-h-24 rounded-xl border border-border-default bg-background px-3 py-2 text-sm text-foreground outline-none transition-all focus-visible:ring-2 focus-visible:ring-accent"
                          onChange={(event) =>
                            setTrialFeedbackByApp((current) => ({
                              ...current,
                              [app.id]: event.target.value,
                            }))
                          }
                          value={trialFeedbackByApp[app.id] ?? ""}
                        />
                      </label>

                      <div className="flex flex-wrap gap-2">
                        <Button
                          disabled={isBusy}
                          onClick={() => void handleTrialDecision(app.id, "pass")}
                        >
                          Pass Trial
                        </Button>
                        <Button
                          disabled={isBusy}
                          onClick={() => void handleTrialDecision(app.id, "fail")}
                          variant="destructive"
                        >
                          Fail Trial
                        </Button>
                      </div>
                    </div>
                  ) : null}

                  {openFeedbackId === app.id && feedbackAction && (
                    <div className="mt-4 grid gap-3 rounded-xl bg-surface-2 p-4 border border-border-default">
                      {feedbackAction === "needs_info" && (
                        <div className="flex flex-wrap gap-2">
                          {NEEDS_INFO_PRESETS.map((preset) => (
                            <button
                              key={preset.label}
                              type="button"
                              onClick={() => setFeedbackText(preset.text)}
                              className="min-h-9 rounded-lg border border-border-default bg-background px-3 py-1 text-xs font-medium text-foreground-muted transition hover:border-accent hover:text-foreground"
                            >
                              {preset.label}
                            </button>
                          ))}
                        </div>
                      )}
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
                      {/* Enable only the valid transitions for the current
                          capability status: active can suspend/revoke,
                          suspended can reinstate/revoke, revoked is terminal. */}
                      <Button
                        variant="destructive"
                        disabled={isBusy || app.capability_status !== "active"}
                        onClick={() => {
                          setCapabilityAction("suspend");
                          setOpenCapabilityId(openCapabilityId === app.org_id ? null : app.org_id);
                        }}
                      >
                        Suspend
                      </Button>
                      <Button
                        variant="secondary"
                        disabled={isBusy || app.capability_status !== "suspended"}
                        onClick={() => {
                          setCapabilityAction("reinstate");
                          setOpenCapabilityId(openCapabilityId === app.org_id ? null : app.org_id);
                        }}
                      >
                        Reinstate
                      </Button>
                      <Button
                        variant="destructive"
                        disabled={
                          isBusy ||
                          (app.capability_status !== "active" &&
                            app.capability_status !== "suspended")
                        }
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
