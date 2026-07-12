"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { listMyOrganizationsV1OrgsMineGet } from "@/lib/generated/sdk.gen";
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

  useEffect(() => {
    async function loadOrgs() {
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
    }
    loadOrgs();
  }, []);

  return (
    <div className="mx-auto w-full max-w-7xl px-4 py-10 md:py-16">
      <div className="mb-8 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="font-heading text-3xl font-bold text-foreground tracking-tight">
            Organizations
          </h1>
          <p className="mt-2 text-foreground-muted">
            Manage your organization memberships and capabilities.
          </p>
        </div>
        <div className="flex flex-col gap-2 sm:flex-row">
          <Link
            href="/dashboard/organizations/become-attestor"
            className="inline-flex min-h-[44px] items-center justify-center rounded-control border border-border-default bg-surface-1 px-4 text-sm font-medium text-foreground transition hover:border-accent/30"
          >
            Become an Attestor
          </Link>
          <Button onClick={() => setIsCreateOpen(true)}>Create Organization</Button>
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
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
          {orgs.map((item) => (
            <Link
              key={item.org.id}
              href={`/dashboard/organizations/${item.org.id}`}
              className="group block rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm transition hover:border-accent/30 hover:shadow-bento"
            >
              <div className="mb-4 flex items-center justify-between">
                <h2 className="font-heading text-lg font-bold text-foreground">
                  {item.org.name}
                </h2>
                <div className="rounded-badge bg-surface-2 px-2 py-1 text-xs font-medium text-foreground-muted">
                  {item.role}
                </div>
              </div>
              {item.org.description && (
                <p className="mb-4 line-clamp-2 text-sm text-foreground-muted">
                  {item.org.description}
                </p>
              )}
              {Object.keys(item.capabilities).length > 0 && (
                <div className="flex flex-wrap gap-2 mt-4 border-t border-border-default pt-4">
                  {Object.entries(item.capabilities).map(([cap, status]) => (
                    <Badge
                      key={cap}
                      variant={
                        status === "active"
                          ? "success"
                          : status === "pending"
                            ? "warning"
                            : "error"
                      }
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
        <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-border-default bg-surface-1 py-24 text-center">
          <h3 className="mb-2 font-heading text-xl font-bold text-foreground">
            No organizations yet
          </h3>
          <p className="mb-6 max-w-sm text-sm text-foreground-muted">
            Create an organization to collaborate with your team, manage shared capabilities, and access the marketplace.
          </p>
          <Button onClick={() => setIsCreateOpen(true)}>Create Organization</Button>
          <Link
            href="/dashboard/organizations/become-attestor"
            className="mt-3 inline-flex min-h-[44px] items-center justify-center text-sm font-medium text-accent hover:underline"
          >
            Become an Attestor
          </Link>
        </div>
      )}

      <CreateOrganizationDialog
        open={isCreateOpen}
        onClose={() => setIsCreateOpen(false)}
      />
    </div>
  );
}
