"use client";

/**
 * Admin developer-application review panel.
 *
 * Lists Developer Platform applications and lets an admin approve or reject a
 * pending one with optional feedback, gated by TOTP. Approval is what mints the
 * developer's account and unlocks API keys, so without this surface the whole
 * developer feature is stuck at "pending".
 *
 * Maps to: FR-DEV-002.
 */
import { useEffect, useState } from "react";

import { TotpInput } from "@/components/modules/auth/totp-input";
import { Button } from "@/components/ui/button";
import { TableSkeleton } from "@/components/ui/skeletons/table-skeleton";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import {
  listDeveloperApplicationsForAdminV1AdminDeveloperApplicationsGet,
  reviewDeveloperApplicationV1AdminDeveloperApplicationsApplicationIdReviewPost,
} from "@/lib/generated/sdk.gen";
import type { DeveloperApplicationResponse } from "@/lib/generated/types.gen";
import { formatLabel } from "@/lib/marketplace/format";

type StatusFilter = "pending" | "approved" | "rejected" | "withdrawn";

const STATUS_FILTERS: StatusFilter[] = [
  "pending",
  "approved",
  "rejected",
  "withdrawn",
];

/**
 * Format one application timestamp for compact admin copy.
 *
 * @param value - API timestamp string.
 */
function formatTimestamp(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(parsed);
}

/**
 * Render the developer-application review queue for admins.
 */
export function AdminDeveloperApplicationsPanel() {
  const [applications, setApplications] = useState<
    DeveloperApplicationResponse[] | null
  >(null);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("pending");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [feedback, setFeedback] = useState("");
  const [totpCode, setTotpCode] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;

    async function load(): Promise<void> {
      setLoading(true);
      configureBrowserClient();
      const result =
        await listDeveloperApplicationsForAdminV1AdminDeveloperApplicationsGet({
          headers: getAccessTokenHeaders(),
          query: { status: statusFilter },
        });
      if (!mounted) {
        return;
      }
      setLoading(false);
      if (!result.response.ok || !result.data) {
        setError(describeGeneratedError(result.error));
        return;
      }
      setError(null);
      setApplications(result.data.applications);
    }

    void load();
    return () => {
      mounted = false;
    };
  }, [statusFilter]);

  /**
   * Reset the inline review form.
   */
  function resetForm(): void {
    setSelectedId(null);
    setFeedback("");
    setTotpCode("");
  }

  const canReview = !pending && totpCode.trim().length >= 6;

  async function handleReview(
    applicationId: string,
    decision: "approved" | "rejected",
  ): Promise<void> {
    setPending(true);
    setError(null);
    configureBrowserClient();
    const result =
      await reviewDeveloperApplicationV1AdminDeveloperApplicationsApplicationIdReviewPost(
        {
          body: {
            decision,
            feedback: feedback.trim() || null,
            totp_code: totpCode.trim(),
          },
          headers: getAccessTokenHeaders(),
          path: { application_id: applicationId },
        },
      );
    setPending(false);
    if (!result.response.ok || !result.data) {
      setError(describeGeneratedError(result.error));
      return;
    }
    // Reviewed applications leave the current (pending) filter view.
    setApplications((current) =>
      current ? current.filter((row) => row.id !== applicationId) : current,
    );
    resetForm();
  }

  if (loading && applications === null) {
    return <TableSkeleton />;
  }

  const rows = applications ?? [];

  return (
    <section className="grid gap-6">
      <header className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
        <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
          Admin developer
        </p>
        <h2 className="mt-2 font-heading text-3xl font-bold text-foreground">
          Developer applications
        </h2>
        <p className="mt-3 max-w-3xl text-sm leading-6 text-foreground-muted">
          Review Developer Platform applications. Approving one provisions the
          developer account and unlocks API keys. Decisions require 2FA.
        </p>
      </header>

      <nav
        aria-label="Filter applications by status"
        className="flex flex-wrap gap-1 rounded-2xl border border-border-default bg-surface-1 p-1.5 shadow-sm"
      >
        {STATUS_FILTERS.map((value) => {
          const isActive = statusFilter === value;
          return (
            <button
              aria-pressed={isActive}
              className={[
                "min-h-11 rounded-xl px-4 text-sm font-semibold capitalize transition-all outline-none focus-visible:ring-2 focus-visible:ring-accent",
                isActive
                  ? "bg-foreground text-background shadow-sm"
                  : "text-foreground-muted hover:bg-surface-2 hover:text-foreground",
              ].join(" ")}
              key={value}
              onClick={() => {
                resetForm();
                setStatusFilter(value);
              }}
              type="button"
            >
              {value}
            </button>
          );
        })}
      </nav>

      {error ? (
        <div className="rounded-2xl border border-error/30 bg-error/10 p-4 text-sm text-error">
          {error}
        </div>
      ) : null}

      {rows.length === 0 ? (
        <div className="rounded-2xl border border-border-default bg-surface-1 p-8 text-center text-sm text-foreground-muted">
          No {statusFilter} applications.
        </div>
      ) : null}

      <div className="grid gap-4">
        {rows.map((application) => {
          const isSelected = selectedId === application.id;
          const isPending = application.status === "pending";
          return (
            <article
              className="grid gap-3 rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm"
              key={application.id}
            >
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="grid gap-1">
                  <h3 className="font-heading text-lg font-bold text-foreground">
                    {application.company_name}
                  </h3>
                  {application.website ? (
                    <a
                      className="text-sm font-semibold text-accent hover:underline"
                      href={application.website}
                      rel="noreferrer noopener"
                      target="_blank"
                    >
                      {application.website}
                    </a>
                  ) : null}
                  <p className="mt-1 text-sm leading-6 text-foreground-muted">
                    {application.use_case}
                  </p>
                  <p className="text-xs text-foreground-muted">
                    Applied {formatTimestamp(application.created_at)}
                  </p>
                </div>
                <span
                  className={[
                    "inline-flex items-center rounded-badge border px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wider",
                    application.status === "approved"
                      ? "border-success/30 bg-success/10 text-success"
                      : application.status === "rejected"
                        ? "border-error/30 bg-error/10 text-error"
                        : "border-warning/30 bg-warning/10 text-warning",
                  ].join(" ")}
                >
                  {formatLabel(application.status)}
                </span>
              </div>

              {application.admin_feedback ? (
                <p className="rounded-xl bg-surface-2 p-3 text-xs text-foreground-muted">
                  <span className="font-semibold text-foreground">Feedback: </span>
                  {application.admin_feedback}
                </p>
              ) : null}

              {isPending ? (
                isSelected ? (
                  <div className="grid gap-4 rounded-xl border border-border-default bg-surface-2 p-4">
                    <label className="grid gap-2 text-sm font-semibold text-foreground">
                      Feedback (optional)
                      <textarea
                        className="min-h-20 rounded-xl border border-border-default bg-background px-4 py-3 text-sm text-foreground outline-none transition-colors focus-visible:ring-2 focus-visible:ring-accent"
                        onChange={(event) => setFeedback(event.target.value)}
                        placeholder="Shared with the applicant on rejection."
                        value={feedback}
                      />
                    </label>
                    <TotpInput onChange={setTotpCode} value={totpCode} />
                    <div className="flex flex-wrap gap-3">
                      <Button
                        disabled={!canReview}
                        onClick={() =>
                          void handleReview(application.id, "approved")
                        }
                      >
                        Approve
                      </Button>
                      <Button
                        disabled={!canReview}
                        onClick={() =>
                          void handleReview(application.id, "rejected")
                        }
                        variant="destructive"
                      >
                        Reject
                      </Button>
                      <Button onClick={resetForm} variant="secondary">
                        Cancel
                      </Button>
                    </div>
                  </div>
                ) : (
                  <div>
                    <Button onClick={() => setSelectedId(application.id)}>
                      Review
                    </Button>
                  </div>
                )
              ) : null}
            </article>
          );
        })}
      </div>
    </section>
  );
}
