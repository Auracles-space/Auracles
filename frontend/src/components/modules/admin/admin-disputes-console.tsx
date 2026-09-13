"use client";

/**
 * Admin disputes console: Attestation and Project disputes as two tabs.
 *
 * Both dispute kinds resolve here, but their escrow mechanics differ
 * (Attestations take a three-outcome verdict; Projects settle release,
 * refund, or split amounts), so each keeps its own panel. Tabs replace the
 * stacked layout so an admin sees one queue at a time with a count on each.
 */
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { AdminAttestationDisputesPanel } from "@/components/modules/admin/admin-attestation-disputes-panel";
import { AdminDisputesPanel } from "@/components/modules/admin/admin-disputes-panel";
import { Tabs, tabId, tabPanelId } from "@/components/ui/tabs";
import { configureBrowserClient, getAccessTokenHeaders } from "@/lib/auth/form-client";
import {
  listAdminAttestationDisputes,
  listAdminProjectDisputes,
} from "@/lib/generated/sdk.gen";

type DisputesTab = "attestation" | "project";

function isTab(value: string | null): value is DisputesTab {
  return value === "attestation" || value === "project";
}

/**
 * Render the tabbed disputes console with active counts on each tab.
 */
export function AdminDisputesConsole() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const requested = searchParams?.get("tab") ?? null;
  const [active, setActive] = useState<DisputesTab>(isTab(requested) ? requested : "attestation");
  const [attestationCount, setAttestationCount] = useState(0);
  const [projectCount, setProjectCount] = useState(0);

  useEffect(() => {
    if (isTab(requested) && requested !== active) {
      setActive(requested);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [requested]);

  useEffect(() => {
    let cancelled = false;
    async function loadCounts() {
      configureBrowserClient();
      const headers = getAccessTokenHeaders();
      try {
        const [attestation, project] = await Promise.all([
          listAdminAttestationDisputes({ headers, query: { status: "active" } }),
          listAdminProjectDisputes({ headers }),
        ]);
        if (cancelled) {
          return;
        }
        if (attestation.response.ok && attestation.data) {
          setAttestationCount(attestation.data.disputes.length);
        }
        if (project.response.ok && project.data) {
          // The Project list has no "active" filter; count the unresolved rows.
          setProjectCount(
            project.data.disputes.filter((dispute: { status: string }) => dispute.status !== "resolved").length,
          );
        }
      } catch {
        // Counts are hints; each panel reports its own load errors.
      }
    }
    void loadCounts();
    return () => {
      cancelled = true;
    };
  }, []);

  function select(id: string) {
    if (!isTab(id)) {
      return;
    }
    setActive(id);
    const params = new URLSearchParams(searchParams?.toString() ?? "");
    params.set("tab", id);
    router.replace(`${pathname}?${params.toString()}`, { scroll: false });
  }

  return (
    <section className="grid gap-6">
      <div className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
        <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">Trust</p>
        <h1 className="mt-2 font-heading text-3xl font-bold text-foreground">Disputes</h1>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-foreground-muted">
          Every verdict moves escrow. Each option states where the money goes before you
          confirm, and confirming asks for a step-up code once per window.
        </p>
      </div>

      <Tabs
        activeId={active}
        label="Dispute queues"
        onChange={select}
        tabs={[
          { id: "attestation", label: "Attestation", count: attestationCount },
          { id: "project", label: "Project", count: projectCount },
        ]}
      />

      <div aria-labelledby={tabId(active)} id={tabPanelId(active)} role="tabpanel">
        {active === "attestation" ? <AdminAttestationDisputesPanel /> : <AdminDisputesPanel />}
      </div>
    </section>
  );
}
