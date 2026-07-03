"use client";

import { useEffect, useState, ReactNode } from "react";
import { useRouter, usePathname } from "next/navigation";
import { listMyOrganizationsV1OrgsMineGet } from "@/lib/generated/sdk.gen";
import type { MyOrganizationResponse } from "@/lib/generated/types.gen";
import { getAccessTokenHeaders } from "@/lib/auth/form-client";
import { OrganizationProvider } from "./organization-context";
import { Tabs } from "@/components/ui/tabs";
import { Spinner } from "@/components/ui/spinner";
import { ExclamationTriangleIcon } from "@radix-ui/react-icons";

type OrganizationShellProps = {
  orgId: string;
  children: ReactNode;
};

export function OrganizationShell({ orgId, children }: OrganizationShellProps) {
  const router = useRouter();
  const pathname = usePathname();

  const [myOrg, setMyOrg] = useState<MyOrganizationResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function loadOrg() {
      try {
        const result = await listMyOrganizationsV1OrgsMineGet({
          headers: getAccessTokenHeaders(),
        });
        if (result.response.ok && result.data) {
          const found = result.data.organizations.find((o: any) => o.org.id === orgId);
          if (found) {
            setMyOrg(found);
          } else {
            setError("Organization not found or you do not have access.");
          }
        } else {
          setError("Failed to load organization.");
        }
      } catch (err) {
        setError("An error occurred.");
      } finally {
        setLoading(false);
      }
    }
    loadOrg();
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

  const tabs = [
    { id: "", label: "Profile" },
    { id: "members", label: "Members" },
  ];
  if (isAdmin) {
    tabs.push({ id: "invitations", label: "Invitations" });
    tabs.push({ id: "teams", label: "Teams" });
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
    <OrganizationProvider orgId={orgId} role={role} org={myOrg.org}>
      <div className="mx-auto w-full max-w-7xl px-4 py-8 md:py-12">
        <div className="mb-6">
          <h1 className="font-heading text-3xl font-bold text-foreground">
            {myOrg.org.name}
          </h1>
          <p className="text-sm text-foreground-muted">
            Manage organization settings and members. Your role: <span className="font-semibold text-foreground capitalize">{role}</span>
          </p>
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
        
        <div className="min-h-[400px]">
          {children}
        </div>
      </div>
    </OrganizationProvider>
  );
}

function OrganizationSuspendedBanner() {
  const { isSuspended } = require("./organization-context").useOrganization();

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
