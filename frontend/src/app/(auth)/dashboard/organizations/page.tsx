"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { listMyOrganizationsV1OrgsMineGet } from "@/lib/generated/sdk.gen";
import { useRefetchOnFocus } from "@/lib/hooks/use-refetch-on-focus";
import type { MyOrganizationResponse } from "@/lib/generated/types.gen";
import { getAccessTokenHeaders } from "@/lib/auth/form-client";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { Badge } from "@/components/ui/badge";
import { CreateOrganizationDialog } from "@/components/modules/organizations/create-organization-dialog";

export default function OrganizationsPage() {
  const [orgs, setOrgs] = useState<MyOrganizationResponse[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isCreateOpen, setIsCreateOpen] = useState(false);

  const loadOrgs = useCallback(async () => {
    try {
      const result = await listMyOrganizationsV1OrgsMineGet({
        headers: getAccessTokenHeaders(),
      });
      if (result.response.ok && result.data) {
        setOrgs(result.data.organizations);
      } else {
        setError("Failed to load organizations");
      }
    } catch {
      setError("An error occurred while loading organizations.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadOrgs();
  }, [loadOrgs]);

  // Refresh the offer dots when the user returns to the tab.
  useRefetchOnFocus(loadOrgs);

  return (
    <div className="mx-auto w-full max-w-7xl px-4 py-10 md:py-16">
      <div className="mb-10 relative overflow-hidden rounded-3xl border border-border-default bg-surface-1 p-8 shadow-sm">
        <div className="absolute -right-20 -top-20 h-64 w-64 rounded-full bg-accent/10 blur-3xl" />
        <div className="relative flex flex-col gap-6 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h1 className="font-heading text-3xl font-bold text-foreground tracking-tight">
              Organizations
            </h1>
            <p className="mt-2 max-w-lg text-foreground-muted">
              Manage your organization memberships, capabilities, and settings across the Auracles network.
            </p>
          </div>
          <div className="flex flex-col gap-3 sm:flex-row">
            <Link
              href="/dashboard/organizations/become-attestor"
              className="inline-flex min-h-12 items-center justify-center rounded-xl border border-border-default bg-background px-5 text-sm font-semibold text-foreground transition hover:border-accent/50 hover:bg-surface-2"
            >
              Become an Attestor
            </Link>
            <Button onClick={() => setIsCreateOpen(true)} className="min-h-12 rounded-xl px-6">
              Create Organization
            </Button>
          </div>
        </div>
      </div>

      {loading ? (
        <div className="flex justify-center py-20">
          <Spinner className="h-8 w-8 text-accent" />
        </div>
      ) : error ? (
        <div className="rounded-2xl border border-error/50 bg-error/5 p-6 text-center text-error">
          {error}
        </div>
      ) : orgs && orgs.length > 0 ? (
        <div className="grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-3">
          {orgs.map((item) => (
            <Link
              key={item.org.id}
              href={`/dashboard/organizations/${item.org.id}`}
              className="group relative flex h-full flex-col overflow-hidden rounded-3xl border border-border-default bg-surface-1 p-7 shadow-sm transition-all duration-300 hover:-translate-y-1 hover:border-accent/40 hover:shadow-bento"
            >
              <div className="absolute inset-0 bg-gradient-to-br from-accent/0 to-accent/0 transition-colors duration-300 group-hover:from-accent/[0.03] group-hover:to-transparent" />
              
              <div className="relative mb-6 flex items-start justify-between gap-4">
                <h2 className="font-heading text-xl font-bold text-foreground">
                  {item.org.name}
                </h2>
                <div className="flex shrink-0 items-center gap-2">
                  {item.counts?.offers ? (
                    <span
                      aria-label={`${item.counts.offers} attestation offer${item.counts.offers === 1 ? "" : "s"} to review`}
                      className="h-2.5 w-2.5 rounded-full bg-accent ring-4 ring-accent/15"
                      title="Attestation offers to review"
                    />
                  ) : null}
                  <div className="inline-flex items-center justify-center rounded-full bg-surface-3 px-3 py-1 text-xs font-bold uppercase tracking-wider text-foreground-muted">
                    {item.role}
                  </div>
                </div>
              </div>
              
              <div className="relative mb-6 flex-1">
                <p className="line-clamp-2 text-sm text-foreground-muted">
                  {item.org.description || "No description provided."}
                </p>
              </div>
              
              {Object.keys(item.capabilities).length > 0 && (
                <div className="relative mt-auto flex flex-wrap gap-2 border-t border-border-default pt-5">
                  {Object.entries(item.capabilities).map(([cap, status]) => (
                    <Badge
                      key={cap}
                      variant={
                        status === "active"
                          ? "success"
                          : status === "pending"
                            ? "warning"
                            : "default"
                      }
                      className="capitalize"
                    >
                      {cap}: {status}
                    </Badge>
                  ))}
                </div>
              )}
            </Link>
          ))}
        </div>
      ) : (
        <div className="flex flex-col items-center justify-center rounded-3xl border border-dashed border-border-strong bg-surface-1/50 py-24 text-center">
          <div className="mb-6 flex h-20 w-20 items-center justify-center rounded-full bg-surface-2 text-accent shadow-sm">
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-10 w-10">
              <path d="M3 21h18"></path><path d="M5 21v-4"></path><path d="M19 21v-4"></path><path d="M3 7h18"></path><path d="M5 7V3"></path><path d="M19 7V3"></path><path d="M12 3v18"></path><path d="M12 11h-4"></path><path d="M12 15h-4"></path><path d="M12 7h-4"></path><path d="M16 11h-4"></path><path d="M16 15h-4"></path><path d="M16 7h-4"></path>
            </svg>
          </div>
          <h3 className="mb-3 font-heading text-2xl font-bold text-foreground">
            No organizations yet
          </h3>
          <p className="mb-8 max-w-md text-base text-foreground-muted">
            Create an organization to collaborate with your team, manage shared capabilities, and access the marketplace.
          </p>
          <Button onClick={() => setIsCreateOpen(true)} className="min-h-12 rounded-xl px-8 shadow-bento">
            Create Organization
          </Button>
        </div>
      )}

      <CreateOrganizationDialog
        open={isCreateOpen}
        onClose={() => setIsCreateOpen(false)}
      />
    </div>
  );
}
