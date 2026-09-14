"use client";

/**
 * Admin organization detail: one place to see everything about an
 * organization before acting on it.
 *
 * The overview loads with the page (the header needs it); every other tab
 * loads its own endpoint the first time it opens and stays mounted (hidden)
 * afterwards, so switching back never refetches. The active tab lives in
 * `?tab=` so a link can land on, say, the audit trail.
 *
 * Maps to: organizations end-to-end design, Decision 1 and Slice D.
 */
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { OrgAttestationsTab } from "@/components/modules/admin/org-detail/org-attestations-tab";
import { OrgAuditTab } from "@/components/modules/admin/org-detail/org-audit-tab";
import { OrgDetailHeader } from "@/components/modules/admin/org-detail/org-detail-header";
import { PanelError, PanelSkeleton } from "@/components/modules/admin/org-detail/org-detail-states";
import { OrgFinancialsTab } from "@/components/modules/admin/org-detail/org-financials-tab";
import { OrgFrameworksTab } from "@/components/modules/admin/org-detail/org-frameworks-tab";
import { OrgMembersTab } from "@/components/modules/admin/org-detail/org-members-tab";
import { OrgOverviewTab } from "@/components/modules/admin/org-detail/org-overview-tab";
import { OrgVerificationTab } from "@/components/modules/admin/org-detail/org-verification-tab";
import { useAdminOrgResource } from "@/components/modules/admin/org-detail/use-admin-org-resource";
import { Tabs, tabId, tabPanelId } from "@/components/ui/tabs";
import { adminOrgOverviewV1AdminOrgsOrgIdDetailGet } from "@/lib/generated/sdk.gen";
import type { AdminOrgOverviewResponse } from "@/lib/generated/types.gen";

const TABS = [
  { id: "overview", label: "Overview" },
  { id: "members", label: "Members" },
  { id: "verification", label: "Verification" },
  { id: "financials", label: "Financials" },
  { id: "frameworks", label: "Frameworks" },
  { id: "attestations", label: "Attestations" },
  { id: "audit", label: "Audit" },
] as const;

type DetailTab = (typeof TABS)[number]["id"];

/** Narrow a query value to a known tab id. */
function isTab(value: string | null | undefined): value is DetailTab {
  return TABS.some((tab) => tab.id === value);
}

/**
 * Render the admin detail page for one organization.
 *
 * @param orgId - Organization id from the route.
 */
export function AdminOrgDetail({ orgId }: { orgId: string }) {
  const router = useRouter();
  const pathname = usePathname();
  const requested = useSearchParams()?.get("tab");
  const initial: DetailTab = isTab(requested) ? requested : "overview";
  const [active, setActive] = useState<DetailTab>(initial);
  const [visited, setVisited] = useState<Set<DetailTab>>(() => new Set([initial]));

  const loadOverview = useCallback(
    (headers: Record<string, string>) =>
      adminOrgOverviewV1AdminOrgsOrgIdDetailGet({ headers, path: { org_id: orgId } }),
    [orgId],
  );
  const overview = useAdminOrgResource<AdminOrgOverviewResponse>(loadOverview);

  function open(id: DetailTab) {
    setActive(id);
    setVisited((previous) => (previous.has(id) ? previous : new Set(previous).add(id)));
  }

  useEffect(() => {
    if (isTab(requested) && requested !== active) open(requested);
    // Only follow external URL changes; local selection already updated state.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [requested]);

  function select(id: string) {
    if (!isTab(id)) return;
    open(id);
    router.replace(`${pathname}?tab=${id}`, { scroll: false });
  }

  if (!overview.data) {
    return overview.error ? (
      <PanelError message={overview.error} onRetry={overview.retry} />
    ) : (
      <PanelSkeleton />
    );
  }
  const org = overview.data;

  const panels: Record<DetailTab, () => React.ReactNode> = {
    overview: () => <OrgOverviewTab onChange={overview.setData} org={org} />,
    members: () => <OrgMembersTab orgId={orgId} />,
    verification: () => <OrgVerificationTab orgId={orgId} />,
    financials: () => <OrgFinancialsTab orgId={orgId} />,
    frameworks: () => <OrgFrameworksTab orgId={orgId} />,
    attestations: () => <OrgAttestationsTab orgId={orgId} />,
    audit: () => <OrgAuditTab orgId={orgId} />,
  };

  return (
    <div className="grid min-w-0 gap-6">
      <OrgDetailHeader org={org} />
      <Tabs activeId={active} label="Organization detail" onChange={select} tabs={[...TABS]} />
      {TABS.filter((tab) => visited.has(tab.id)).map((tab) => (
        <div
          aria-labelledby={tabId(tab.id)}
          hidden={tab.id !== active}
          id={tabPanelId(tab.id)}
          key={tab.id}
          role="tabpanel"
        >
          {panels[tab.id]()}
        </div>
      ))}
    </div>
  );
}
