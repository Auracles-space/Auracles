"use client";

/**
 * Attestor application queue for admins.
 *
 * `mode="applications"` lists applications by status with a filter;
 * `mode="trials"` lists every application with a calibration trial in
 * flight (assigned, submitted, or failed) with the cards open so the grader
 * is one glance away. Both share one loader and one local update path.
 */
import { useCallback, useEffect, useState } from "react";

import { SegmentedControl } from "@/components/ui/segmented-control";
import { TableSkeleton } from "@/components/ui/skeletons/table-skeleton";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import {
  adminListCalibrationFixturesV1AdminOrgAttestorApplicationsCalibrationFixturesGet as listFixtures,
  listOrgAttestorApplicationsForAdmin,
} from "@/lib/generated/sdk.gen";
import type {
  CalibrationFixtureItem,
  OrgAttestorAdminListItem,
} from "@/lib/generated/types.gen";

import { AttestorApplicationCard } from "./attestor-application-card";

export type ApplicationStatusFilter = "submitted" | "needs_info" | "approved" | "rejected";

const FILTERS: { value: ApplicationStatusFilter; label: string }[] = [
  { value: "submitted", label: "Submitted" },
  { value: "needs_info", label: "Needs info" },
  { value: "approved", label: "Approved" },
  { value: "rejected", label: "Rejected" },
];

type AttestorApplicationQueueProps = {
  mode: "applications" | "trials";
  /** Reports the submitted count whenever that filter loads, for the tab badge. */
  onCountChange?: (count: number) => void;
};

/**
 * Render the application or trial queue.
 *
 * @param props - Queue mode and count reporter.
 */
export function AttestorApplicationQueue({ mode, onCountChange }: AttestorApplicationQueueProps) {
  const [filter, setFilter] = useState<ApplicationStatusFilter>("submitted");
  const [applications, setApplications] = useState<OrgAttestorAdminListItem[]>([]);
  const [fixtures, setFixtures] = useState<CalibrationFixtureItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const status = mode === "trials" ? "trial" : filter;

  const load = useCallback(async () => {
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
        return;
      }
      setApplications(result.data.applications);
      if (status === "submitted") {
        onCountChange?.(result.data.applications.length);
      }
    } catch {
      setError("The queue could not be loaded.");
    } finally {
      setLoading(false);
    }
    // onCountChange is a parent setter; including it would refetch on every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    let cancelled = false;
    async function loadFixtures() {
      configureBrowserClient();
      try {
        const result = await listFixtures({ headers: getAccessTokenHeaders() });
        if (!cancelled && result.response.ok && result.data) {
          setFixtures(result.data.fixtures);
        }
      } catch {
        // The fixture picker shows an empty list; starting a trial then fails
        // loudly through the action's own error path.
      }
    }
    void loadFixtures();
    return () => {
      cancelled = true;
    };
  }, []);

  function applyUpdate(applicationId: string, patch: Partial<OrgAttestorAdminListItem>) {
    setApplications((current) =>
      current.map((item) => (item.id === applicationId ? { ...item, ...patch } : item)),
    );
  }

  function showNotice(message: string) {
    setError(null);
    setNotice(message);
  }

  function showError(message: string) {
    setNotice(null);
    setError(message);
  }

  return (
    <section className="grid gap-4">
      {mode === "applications" ? (
        <SegmentedControl
          className="max-w-2xl"
          label="Filter applications by status"
          onChange={setFilter}
          options={FILTERS}
          value={filter}
        />
      ) : (
        <p className="text-sm text-foreground-muted">
          Trials assigned, awaiting a grade, or failed. Grade a submitted trial to move the
          application on to approval.
        </p>
      )}

      {error ? (
        <p className="rounded-xl border border-error/30 bg-error/10 p-4 text-sm text-error" role="alert">
          {error}
        </p>
      ) : null}
      {notice ? (
        <p className="rounded-xl border border-success/30 bg-success/10 p-4 text-sm text-success" role="status">
          {notice}
        </p>
      ) : null}

      {loading ? (
        <TableSkeleton />
      ) : applications.length === 0 ? (
        <p className="rounded-2xl border border-border-default bg-surface-1 p-6 text-sm text-foreground-muted shadow-sm">
          {mode === "trials" ? "No trials in flight." : "No applications in this status."}
        </p>
      ) : (
        <div className="grid gap-3">
          {applications.map((app) => (
            <AttestorApplicationCard
              app={app}
              defaultOpen={mode === "trials"}
              fixtures={fixtures}
              key={app.id}
              onError={showError}
              onNotice={showNotice}
              onUpdate={applyUpdate}
            />
          ))}
        </div>
      )}
    </section>
  );
}
