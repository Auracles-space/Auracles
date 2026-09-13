"use client";

/**
 * Admin organization directory with platform-wide suspend / reinstate.
 *
 * Suspending removes every member's derived marketplace roles at once, so
 * the action confirms through the shared dialog, collects a required reason
 * that the organization's owner will see, and requires an open step-up
 * window; a failed call shows its error inside the dialog. Reinstate needs
 * no reason.
 */
import { useEffect, useId, useState } from "react";
import {
  adminListOrgsV1AdminOrgsGet,
  adminSuspendOrgV1AdminOrgsOrgIdSuspendPost,
  adminReinstateOrgV1AdminOrgsOrgIdReinstatePost
} from "@/lib/generated/sdk.gen";
import type { AdminOrgResponse } from "@/lib/generated/types.gen";
import { describeGeneratedError, getAccessTokenHeaders } from "@/lib/auth/form-client";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Spinner } from "@/components/ui/spinner";
import { Input } from "@/components/ui/input";
import { ReasonField, isReasonValid } from "@/components/modules/admin/reason-field";
import { MagnifyingGlassIcon } from "@radix-ui/react-icons";

/**
 * Paginated, searchable directory of every organization with suspend and
 * reinstate controls for platform admins.
 */
export function AdminOrganizationsList() {
  const reasonFieldId = useId();
  const [orgs, setOrgs] = useState<AdminOrgResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Pagination & Search. `searchInput` is the live field text; `committedQuery`
  // is the term actually searched — only updated on submit (Enter or button),
  // so typing does not fire a request per keystroke.
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [searchInput, setSearchInput] = useState("");
  const [committedQuery, setCommittedQuery] = useState("");
  const pageSize = 10;

  // Suspend / Reinstate State. `orgToAct` holds the pending target; `actionKind`
  // distinguishes the confirm-dialog copy and which endpoint fires.
  const [orgToAct, setOrgToAct] = useState<AdminOrgResponse | null>(null);
  const [actionKind, setActionKind] = useState<"suspend" | "reinstate">("suspend");
  const [actionLoading, setActionLoading] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  // Owner-visible reason; required for suspend only, so the confirm button
  // stays disabled until it satisfies the backend length rule.
  const [reason, setReason] = useState("");
  const reasonMissing = actionKind === "suspend" && !isReasonValid(reason);

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
    } catch {
      setError("An error occurred loading organizations.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadOrgs(page, committedQuery);
  }, [page, committedQuery]);

  function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = searchInput.trim();
    const pageWillChange = page !== 1;
    const queryWillChange = trimmed !== committedQuery;
    // Reset to page 1 and commit the term; the effect refetches on either
    // change. When neither changes, submit still refetches so it is never a
    // dead action.
    if (pageWillChange) {
      setPage(1);
    }
    if (queryWillChange) {
      setCommittedQuery(trimmed);
    }
    if (!pageWillChange && !queryWillChange) {
      loadOrgs(1, trimmed);
    }
  }

  async function handleConfirmAction() {
    if (!orgToAct || reasonMissing) return;
    setActionLoading(true);
    setActionError(null);

    try {
      const result =
        actionKind === "suspend"
          ? await adminSuspendOrgV1AdminOrgsOrgIdSuspendPost({
              path: { org_id: orgToAct.id },
              headers: getAccessTokenHeaders(),
              body: { reason: reason.trim() },
            })
          : await adminReinstateOrgV1AdminOrgsOrgIdReinstatePost({
              path: { org_id: orgToAct.id },
              headers: getAccessTokenHeaders(),
            });

      if (!result.response.ok) {
        setActionError(describeGeneratedError(result.error));
        setActionLoading(false);
      } else {
        setActionLoading(false);
        setOrgToAct(null);
        await loadOrgs(page, committedQuery);
      }
    } catch {
      setActionError("An unexpected error occurred.");
      setActionLoading(false);
    }
  }

  /**
   * Open the confirm dialog for a suspend or reinstate action.
   *
   * @param org - Target organization row.
   * @param kind - Whether to suspend an active org or reinstate a suspended one.
   */
  function openAction(org: AdminOrgResponse, kind: "suspend" | "reinstate") {
    setActionKind(kind);
    setActionError(null);
    setReason("");
    setOrgToAct(org);
  }

  /** Dismiss the dialog and drop any half-typed reason so it never leaks to the next target. */
  function closeAction() {
    setOrgToAct(null);
    setActionError(null);
    setReason("");
  }

  const totalPages = Math.ceil(total / pageSize);

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <h2 className="font-heading text-2xl font-bold text-foreground">
          All organizations
        </h2>
        
        <form onSubmit={handleSearch} role="search" className="flex gap-2 w-full sm:w-auto">
          <div className="relative flex-grow sm:w-64">
            {loading ? (
              <Spinner
                aria-label="Searching"
                className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-accent"
              />
            ) : (
              <MagnifyingGlassIcon className="absolute left-3 top-1/2 -translate-y-1/2 text-foreground-muted" />
            )}
            <Input
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              placeholder="Search by name or slug..."
              className="pl-9"
            />
          </div>
          <Button type="submit" variant="secondary" loading={loading}>
            Search
          </Button>
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
                          {Object.keys(org.capabilities).length === 0 ? (
                            <span className="text-xs text-foreground-muted">None</span>
                          ) : (
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
                          )}
                        </td>
                        <td className={`px-6 py-4 font-medium ${statusColor}`}>
                          {statusText}
                        </td>
                        <td className="px-6 py-4 text-right">
                          {isSuspended && !isDeactivated ? (
                            <Button
                              variant="secondary"
                              onClick={() => openAction(org, "reinstate")}
                            >
                              Reinstate
                            </Button>
                          ) : (
                            <Button
                              variant="secondary"
                              disabled={isSuspended || isDeactivated}
                              onClick={() => openAction(org, "suspend")}
                            >
                              Suspend
                            </Button>
                          )}
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
        open={!!orgToAct}
        title={
          actionKind === "suspend"
            ? "Suspend Organization?"
            : "Reinstate Organization?"
        }
        description={
          actionKind === "suspend" ? (
            <>
              <p>
                Are you sure you want to suspend &quot;{orgToAct?.name}&quot;? Members will lose
                access to organization resources immediately.
              </p>
              <ReasonField
                disabled={actionLoading}
                id={reasonFieldId}
                onChange={setReason}
                value={reason}
              />
            </>
          ) : (
            `Reinstate "${orgToAct?.name}"? Members will regain access to organization resources immediately.`
          )
        }
        confirmLabel={actionKind === "suspend" ? "Suspend" : "Reinstate"}
        tone={actionKind === "suspend" ? "danger" : "default"}
        busy={actionLoading || reasonMissing}
        error={actionError}
        onConfirm={handleConfirmAction}
        onClose={closeAction}
      />
    </div>
  );
}
