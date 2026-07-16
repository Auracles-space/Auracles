"use client";

import { useEffect, useState, ReactNode } from "react";
import { useRouter, usePathname } from "next/navigation";
import { listMyOrganizationsV1OrgsMineGet, getOrgNda } from "@/lib/generated/sdk.gen";
import type { MyOrganizationResponse } from "@/lib/generated/types.gen";
import { getAccessTokenHeaders } from "@/lib/auth/form-client";
import { OrganizationProvider } from "./organization-context";
import { Tabs, type TabItem } from "@/components/ui/tabs";
import { Spinner } from "@/components/ui/spinner";
import { ExclamationTriangleIcon } from "@radix-ui/react-icons";
import { useOrganization } from "./organization-context";

type OrganizationShellProps = {
  orgId: string;
  children: ReactNode;
};

export function OrganizationShell({ orgId, children }: OrganizationShellProps) {
  const router = useRouter();
  const pathname = usePathname();

  const [myOrg, setMyOrg] = useState<MyOrganizationResponse | null>(null);
  const [ndaRequired, setNdaRequired] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function loadOrg() {
      try {
        const result = await listMyOrganizationsV1OrgsMineGet({
          headers: getAccessTokenHeaders(),
        });
        if (result.response.ok && result.data) {
          const found = result.data.organizations.find((o: { org: { id: string } }) => o.org.id === orgId);
          if (found) {
            setMyOrg(found);
          } else {
            setError("Organization not found or you do not have access.");
          }
        } else {
          setError("Failed to load organization.");
        }
      } catch {
        setError("An error occurred.");
      } finally {
        setLoading(false);
      }
    }
    loadOrg();
  }, [orgId]);

  // The NDA becomes required as soon as the org has a live attestor
  // application (before the capability exists), so drive the NDA tab off the
  // NDA-status endpoint rather than the capability map.
  useEffect(() => {
    async function loadNda() {
      const res = await getOrgNda({
        path: { org_id: orgId },
        headers: getAccessTokenHeaders(),
      });
      setNdaRequired(res.data?.required ?? false);
    }
    loadNda();
  }, [orgId]);

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Spinner className="h-8 w-8 text-accent" />
      </div>
    );
  }

  if (error || !myOrg) {
    return (
      <div className="mx-auto mt-10 max-w-3xl rounded-2xl border border-error/50 bg-error/5 p-6 text-center text-error">
        {error || "Organization not found."}
      </div>
    );
  }

  const role = myOrg.role;
  const isOwner = role === "owner";
  const isAdmin = role === "admin" || isOwner;

  const operatorCap = myOrg.capabilities?.["operator"];
  const isOperator = operatorCap === "active";

  const attestorCap = myOrg.capabilities?.["attestor"];
  // Required while a live attestor application exists (pre-approval) or the
  // capability is pending/active — computed server-side via the NDA endpoint.
  const needsNda = ndaRequired;
  const attestorActive = attestorCap === "active";

  const contributorCap = myOrg.capabilities?.["contributor"];
  const contributorActive = contributorCap === "active";

  const tabs: TabItem[] = [
    { id: "", label: "Profile" },
    { id: "members", label: "Members" },
    // Any member may be nominated for the attestor calibration trial; the page
    // resolves to a friendly "no active trial" state for non-nominees.
    { id: "attestor-trial", label: "Calibration Trial" },
  ];
  if (needsNda) {
    tabs.push({ id: "nda", label: "NDA" });
  }
  
  const counts = myOrg.counts;
  if (isAdmin) {
    tabs.push({
      id: "invitations",
      label: "Invitations",
      count: counts?.invitations,
    });
    tabs.push({ id: "teams", label: "Teams" });
    tabs.push({ id: "attestor", label: "Attestor" });

    if (isOperator) {
      tabs.push({ id: "operator", label: "Operator" });
      tabs.push({ id: "projects", label: "Projects" });
    }

    if (isOperator || attestorActive || contributorActive) {
      tabs.push({ id: "financials", label: "Financials" });
    }

    tabs.push({ id: "offers", label: "Offers", count: counts?.offers });
    tabs.push({ id: "queue", label: "Queue", count: counts?.queue });
  }
  if (isOwner) {
    tabs.push({ id: "danger-zone", label: "Danger Zone" });
  }

  // Determine active tab based on pathname
  const pathParts = pathname.split("/");
  // /dashboard/organizations/[orgId]/members -> "members"
  // /dashboard/organizations/[orgId] -> ""
  const activeSegment = pathParts.length > 4 ? pathParts[4] : "";
  const activeId = tabs.some((t) => t.id === activeSegment) ? activeSegment : "";

  function handleTabChange(id: string) {
    router.push(`/dashboard/organizations/${orgId}${id ? `/${id}` : ""}`);
  }

  return (
    <OrganizationProvider orgId={orgId} role={role} org={myOrg.org} capabilities={myOrg.capabilities}>
      <div className="mx-auto w-full max-w-7xl px-4 py-8 md:py-12">
        <div className="relative mb-8 overflow-hidden rounded-3xl border border-border-default bg-surface-1 p-8 shadow-sm">
          <div className="absolute -left-20 -top-20 h-64 w-64 rounded-full bg-accent/10 blur-3xl" />
          <div className="relative">
            <h1 className="font-heading text-3xl font-bold text-foreground tracking-tight">
              {myOrg.org.name}
            </h1>
            <p className="mt-2 text-foreground-muted">
              Manage organization settings and members. Your role: <span className="font-semibold text-foreground capitalize">{role}</span>
            </p>
          </div>
        </div>

        <OrganizationSuspendedBanner />

        <div className="mb-8">
          <Tabs
            tabs={tabs}
            activeId={activeId}
            onChange={handleTabChange}
            label="Organization Settings"
          />
        </div>
        
        <div className="min-h-[400px] motion-safe:animate-[fade-in_200ms_ease-out]">
          {children}
        </div>
      </div>
    </OrganizationProvider>
  );
}

function OrganizationSuspendedBanner() {
  const { isSuspended } = useOrganization();

  if (!isSuspended) return null;

  return (
    <div className="mb-6 flex items-start gap-3 rounded-2xl border border-error/50 bg-error/5 p-4 text-error">
      <ExclamationTriangleIcon className="mt-0.5 h-5 w-5 shrink-0" />
      <div>
        <h3 className="font-semibold">Organization Suspended</h3>
        <p className="mt-1 text-sm text-error/80">
          This organization has been suspended. Modification actions are disabled.
        </p>
      </div>
    </div>
  );
}
