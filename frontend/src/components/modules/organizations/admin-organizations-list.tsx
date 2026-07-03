"use client";

import { useEffect, useState } from "react";
import { 
  adminListOrgsV1AdminOrgsGet,
  adminSuspendOrgV1AdminOrgsOrgIdSuspendPost 
} from "@/lib/generated/sdk.gen";
import type { AdminOrgResponse } from "@/lib/generated/types.gen";
import { getAccessTokenHeaders } from "@/lib/auth/form-client";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Spinner } from "@/components/ui/spinner";
import { Input } from "@/components/ui/input";
import { MagnifyingGlassIcon } from "@radix-ui/react-icons";

export function AdminOrganizationsList() {
  const [orgs, setOrgs] = useState<AdminOrgResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Pagination & Search
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [searchQuery, setSearchQuery] = useState("");
  const pageSize = 10;

  // Suspend State
  const [orgToSuspend, setOrgToSuspend] = useState<AdminOrgResponse | null>(null);
  const [suspendLoading, setSuspendLoading] = useState(false);
  const [suspendError, setSuspendError] = useState<string | null>(null);

  async function loadOrgs(currentPage: number, query: string) {
    setLoading(true);
    setError(null);
    try {
      const result = await adminListOrgsV1AdminOrgsGet({
        query: {
          page: currentPage,
          page_size: pageSize,
          query: query || undefined,
        },
        headers: getAccessTokenHeaders(),
      });
      if (result.response.ok && result.data) {
        setOrgs(result.data.orgs);
        setTotal(result.data.total);
      } else {
        setError("Failed to load organizations.");
      }
    } catch (err) {
      setError("An error occurred loading organizations.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadOrgs(page, searchQuery);
  }, [page, searchQuery]);

  async function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    setPage(1); // Reset to first page on new search
    // loadOrgs is called by effect on page change / searchQuery change, but we want 
    // to trigger it only on submit or debounce. To keep it simple, we bind searchQuery to state and let effect run.
  }

  async function handleSuspend() {
    if (!orgToSuspend) return;
    setSuspendLoading(true);
    setSuspendError(null);

    try {
      const result = await adminSuspendOrgV1AdminOrgsOrgIdSuspendPost({
        path: { org_id: orgToSuspend.id },
        headers: getAccessTokenHeaders(),
      });

      if (!result.response.ok) {
        setSuspendError(result.error?.detail?.error_code || "Failed to suspend organization.");
        setSuspendLoading(false);
      } else {
        setSuspendLoading(false);
        setOrgToSuspend(null);
        await loadOrgs(page, searchQuery);
      }
    } catch (err) {
      setSuspendError("An unexpected error occurred.");
      setSuspendLoading(false);
    }
  }

  const totalPages = Math.ceil(total / pageSize);

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <h1 className="font-heading text-2xl font-bold text-foreground">
          Organizations
        </h1>
        
        <form onSubmit={handleSearch} className="flex gap-2 w-full sm:w-auto">
          <div className="relative flex-grow sm:w-64">
            <MagnifyingGlassIcon className="absolute left-3 top-1/2 -translate-y-1/2 text-foreground-muted" />
            <Input 
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search by name or slug..."
              className="pl-9"
            />
          </div>
          <Button type="submit" variant="secondary">Search</Button>
        </form>
      </div>

      <div className="rounded-2xl border border-border-default bg-surface-1 shadow-sm overflow-hidden">
        {loading && orgs.length === 0 ? (
          <div className="flex h-48 items-center justify-center">
            <Spinner className="h-6 w-6 text-accent" />
          </div>
        ) : error ? (
          <div className="p-6 text-center text-error bg-error/5">{error}</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-border-default bg-surface-2 text-foreground-muted">
                <tr>
                  <th className="px-6 py-3 font-semibold">Organization</th>
                  <th className="px-6 py-3 font-semibold">Country</th>
                  <th className="px-6 py-3 font-semibold">Members</th>
                  <th className="px-6 py-3 font-semibold">Capabilities</th>
                  <th className="px-6 py-3 font-semibold">Status</th>
                  <th className="px-6 py-3 font-semibold text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border-default">
                {orgs.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="px-6 py-8 text-center text-foreground-muted">
                      No organizations found.
                    </td>
                  </tr>
                ) : (
                  orgs.map((org) => {
                    const isSuspended = !!org.suspended_at;
                    const isDeactivated = !!org.deactivated_at;
                    const statusText = isDeactivated 
                      ? "Deactivated" 
                      : isSuspended 
                        ? "Suspended" 
                        : "Active";
                    const statusColor = isDeactivated || isSuspended ? "text-error" : "text-success";

                    return (
                      <tr key={org.id} className="hover:bg-surface-2/50 transition-colors">
                        <td className="px-6 py-4">
                          <p className="font-semibold text-foreground">{org.name}</p>
                          <p className="text-xs text-foreground-muted">@{org.slug}</p>
                        </td>
                        <td className="px-6 py-4">{org.country}</td>
                        <td className="px-6 py-4">{org.member_count}</td>
                        <td className="px-6 py-4">
                          <div className="flex flex-wrap gap-1">
                            {Object.entries(org.capabilities).map(([cap, state]) => (
                              <span 
                                key={cap} 
                                className="inline-block rounded bg-surface-3 px-1.5 py-0.5 text-[10px] font-medium text-foreground uppercase tracking-wider"
                                title={`${cap}: ${state}`}
                              >
                                {cap.charAt(0)}
                              </span>
                            ))}
                          </div>
                        </td>
                        <td className={`px-6 py-4 font-medium ${statusColor}`}>
                          {statusText}
                        </td>
                        <td className="px-6 py-4 text-right">
                          <Button
                            variant="secondary"
                                                        disabled={isSuspended || isDeactivated}
                            onClick={() => setOrgToSuspend(org)}
                          >
                            Suspend
                          </Button>
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        )}
        
        {/* Pagination */}
        {total > 0 && (
          <div className="flex items-center justify-between border-t border-border-default px-6 py-4 bg-surface-1">
            <p className="text-sm text-foreground-muted">
              Showing <span className="font-medium text-foreground">{(page - 1) * pageSize + 1}</span> to <span className="font-medium text-foreground">{Math.min(page * pageSize, total)}</span> of <span className="font-medium text-foreground">{total}</span> results
            </p>
            <div className="flex gap-2">
              <Button
                variant="secondary"
                                disabled={page <= 1 || loading}
                onClick={() => setPage(page - 1)}
              >
                Previous
              </Button>
              <Button
                variant="secondary"
                                disabled={page >= totalPages || loading}
                onClick={() => setPage(page + 1)}
              >
                Next
              </Button>
            </div>
          </div>
        )}
      </div>

      <ConfirmDialog
        open={!!orgToSuspend}
        title="Suspend Organization?"
        description={`Are you sure you want to suspend "${orgToSuspend?.name}"? Members will lose access to organization resources immediately.`}
        confirmLabel="Suspend"
        tone="danger"
        busy={suspendLoading}
        onConfirm={handleSuspend}
        onClose={() => setOrgToSuspend(null)}
      />
    </div>
  );
}
