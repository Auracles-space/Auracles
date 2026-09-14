"use client";

/**
 * Admin organization directory with platform-wide suspend / reinstate and
 * per-capability controls.
 *
 * Suspending removes every member's derived marketplace roles at once, so
 * the action confirms through the shared dialog, collects a required reason
 * that the organization's owner will see, and requires an open step-up
 * window; a failed call shows its error inside the dialog. Reinstate needs
 * no reason. Each row also opens a capabilities dialog where the
 * contributor, operator, and attestor capabilities can be suspended,
 * reinstated, or revoked individually with the same reason rule. Closed
 * (deactivated) organizations can be reopened with Reactivate (Decision 4).
 *
 * Below `md` each organization renders as a card; from `md` up as a table.
 *
 * Maps to: organizations end-to-end design, Slice D (directory) and Decision 4.
 */
import { useEffect, useState } from "react";
import { adminListOrgsV1AdminOrgsGet } from "@/lib/generated/sdk.gen";
import type { AdminOrgResponse } from "@/lib/generated/types.gen";
import { describeGeneratedError, getAccessTokenHeaders } from "@/lib/auth/form-client";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { Input } from "@/components/ui/input";
import { OrgCapabilitiesDialog } from "@/components/modules/admin/org-capabilities-dialog";
import type {
  CapabilityStatusAfter,
  OrgCapability,
} from "@/components/modules/admin/org-capability-controls";
import {
  AdminOrgCard,
  AdminOrgTableRow,
  type OrgDirectoryAction,
} from "@/components/modules/admin/admin-org-directory-entry";
import { AdminOrgLifecycleDialog } from "@/components/modules/admin/admin-org-lifecycle-dialog";
import { MagnifyingGlassIcon } from "@radix-ui/react-icons";

/**
 * Paginated, searchable directory of every organization with suspend and
 * reinstate controls for platform admins.
 */
export function AdminOrganizationsList() {
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

  // Lifecycle action target. The confirm dialog owns its own reason, busy,
  // and error state and is mounted only while a target is set.
  const [orgToAct, setOrgToAct] = useState<AdminOrgResponse | null>(null);
  const [actionKind, setActionKind] = useState<OrgDirectoryAction>("suspend");
  // Organization whose capabilities dialog is open, if any.
  const [capabilitiesOrg, setCapabilitiesOrg] = useState<AdminOrgResponse | null>(null);

  /**
   * Reflect a capability transition on the row without a refetch, so the
   * pill and the stored reason update the moment the API confirms.
   */
  function applyCapabilityChange(
    orgId: string,
    capability: OrgCapability,
    status: CapabilityStatusAfter,
    changeReason: string | null,
  ) {
    function patch(org: AdminOrgResponse): AdminOrgResponse {
      if (org.id !== orgId) return org;
      const reasons = { ...(org.capability_reasons ?? {}) };
      if (changeReason) {
        reasons[capability] = changeReason;
      } else {
        delete reasons[capability];
      }
      return {
        ...org,
        capabilities: { ...org.capabilities, [capability]: status },
        capability_reasons: reasons,
      };
    }
    setOrgs((rows) => rows.map(patch));
    setCapabilitiesOrg((current) => (current ? patch(current) : current));
  }

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
        setError(describeGeneratedError(result.error));
      }
    } catch (caught) {
      setError(describeGeneratedError(caught));
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

  /**
   * Open the confirm dialog for a lifecycle action.
   *
   * @param org - Target organization row.
   * @param kind - Suspend an active org, reinstate a suspended one, or reactivate a closed one.
   */
  function openAction(org: AdminOrgResponse, kind: OrgDirectoryAction) {
    setActionKind(kind);
    setOrgToAct(org);
  }

  /** Close the dialog and reload the current page so the row shows its new state. */
  async function handleActionDone() {
    setOrgToAct(null);
    await loadOrgs(page, committedQuery);
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
        ) : orgs.length === 0 ? (
          <p className="px-6 py-8 text-center text-foreground-muted">No organizations found.</p>
        ) : (
          <>
            <ul aria-label="Organizations" className="grid gap-3 p-4 md:hidden">
              {orgs.map((org) => (
                <AdminOrgCard
                  key={org.id}
                  onAction={openAction}
                  onCapabilities={setCapabilitiesOrg}
                  org={org}
                />
              ))}
            </ul>
            <div className="hidden md:block">
              <table className="w-full text-left text-sm">
                <thead className="border-b border-border-default bg-surface-2 text-foreground-muted">
                  <tr>
                    <th className="px-6 py-3 font-semibold">Organization</th>
                    <th className="px-6 py-3 font-semibold">Country</th>
                    <th className="px-6 py-3 font-semibold">Members</th>
                    <th className="px-6 py-3 font-semibold">Capabilities</th>
                    <th className="px-6 py-3 font-semibold">Status</th>
                    <th className="px-6 py-3 font-semibold">KYB</th>
                    <th className="px-6 py-3 font-semibold text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border-default">
                  {orgs.map((org) => (
                    <AdminOrgTableRow
                      key={org.id}
                      onAction={openAction}
                      onCapabilities={setCapabilitiesOrg}
                      org={org}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}

        {/* Pagination */}
        {total > 0 && (
          <div className="flex flex-col gap-3 border-t border-border-default bg-surface-1 px-4 py-4 sm:flex-row sm:items-center sm:justify-between md:px-6">
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

      {capabilitiesOrg ? (
        <OrgCapabilitiesDialog
          onChanged={(capability, status, changeReason) =>
            applyCapabilityChange(capabilitiesOrg.id, capability, status, changeReason)
          }
          onClose={() => setCapabilitiesOrg(null)}
          org={capabilitiesOrg}
        />
      ) : null}

      {orgToAct ? (
        <AdminOrgLifecycleDialog
          kind={actionKind}
          onClose={() => setOrgToAct(null)}
          onDone={handleActionDone}
          org={orgToAct}
        />
      ) : null}
    </div>
  );
}
