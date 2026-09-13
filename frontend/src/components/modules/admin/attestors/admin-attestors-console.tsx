"use client";

/**
 * Admin attestor console: one page for the whole attestor pipeline.
 *
 * Replaces three scattered surfaces (org-attestor review, the application
 * rows on the attestations page, and calibration fixtures) with three tabs:
 * Applications, Trials, Fixtures. The active tab is mirrored to `?tab=` so
 * links and reloads land on the right one.
 *
 * Maps to: docs/superpowers/specs/2026-09-13-step-up-and-admin-console-design.md §4.
 */
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { AdminCalibrationFixturesPanel } from "@/components/modules/admin/admin-calibration-fixtures-panel";
import { Tabs, tabId, tabPanelId } from "@/components/ui/tabs";
import { configureBrowserClient, getAccessTokenHeaders } from "@/lib/auth/form-client";
import { listOrgAttestorApplicationsForAdmin } from "@/lib/generated/sdk.gen";

import { AttestorApplicationQueue } from "./attestor-application-queue";

export type AttestorsTab = "applications" | "trials" | "fixtures";

const TAB_IDS: AttestorsTab[] = ["applications", "trials", "fixtures"];

function isTab(value: string | null): value is AttestorsTab {
  return value !== null && (TAB_IDS as string[]).includes(value);
}

/**
 * Render the attestor pipeline console.
 */
export function AdminAttestorsConsole() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const requested = searchParams?.get("tab") ?? null;
  const [active, setActive] = useState<AttestorsTab>(isTab(requested) ? requested : "applications");
  const [submittedCount, setSubmittedCount] = useState(0);
  const [trialCount, setTrialCount] = useState(0);

  useEffect(() => {
    if (isTab(requested) && requested !== active) {
      setActive(requested);
    }
    // Only follow the URL when it changes; local selection updates the URL below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [requested]);

  // Both counts load once so the tabs can badge before either queue mounts.
  useEffect(() => {
    let cancelled = false;
    async function loadCounts() {
      configureBrowserClient();
      const headers = getAccessTokenHeaders();
      try {
        const [submitted, trials] = await Promise.all([
          listOrgAttestorApplicationsForAdmin({ headers, query: { status: "submitted" } }),
          listOrgAttestorApplicationsForAdmin({ headers, query: { status: "trial" } }),
        ]);
        if (cancelled) {
          return;
        }
        if (submitted.response.ok && submitted.data) {
          setSubmittedCount(submitted.data.applications.length);
        }
        if (trials.response.ok && trials.data) {
          setTrialCount(
            trials.data.applications.filter(
              (app: { trial_status?: string | null }) => app.trial_status === "submitted",
            ).length,
          );
        }
      } catch {
        // Badges are hints; the queues report their own errors.
      }
    }
    void loadCounts();
    return () => {
      cancelled = true;
    };
  }, []);

  const select = useCallback(
    (id: string) => {
      if (!isTab(id)) {
        return;
      }
      setActive(id);
      const params = new URLSearchParams(searchParams?.toString() ?? "");
      params.set("tab", id);
      router.replace(`${pathname}?${params.toString()}`, { scroll: false });
    },
    [pathname, router, searchParams],
  );

  return (
    <section className="grid gap-6">
      <div className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
        <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">Trust</p>
        <h1 className="mt-2 font-heading text-3xl font-bold text-foreground">
          Attestor organizations
        </h1>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-foreground-muted">
          Review applications, grade calibration trials, and manage the fixtures trials run
          on. Business verification is recorded on the Organizations page and read here.
        </p>
      </div>

      <Tabs
        activeId={active}
        label="Attestor pipeline"
        onChange={select}
        tabs={[
          { id: "applications", label: "Applications", count: submittedCount },
          { id: "trials", label: "Trials", count: trialCount },
          { id: "fixtures", label: "Fixtures" },
        ]}
      />

      <div aria-labelledby={tabId(active)} id={tabPanelId(active)} role="tabpanel">
        {active === "applications" ? (
          <AttestorApplicationQueue mode="applications" onCountChange={setSubmittedCount} />
        ) : active === "trials" ? (
          <AttestorApplicationQueue mode="trials" />
        ) : (
          <AdminCalibrationFixturesPanel />
        )}
      </div>
    </section>
  );
}
