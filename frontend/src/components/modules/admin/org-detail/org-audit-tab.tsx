"use client";

/**
 * Audit tab of the admin organization detail page: the organization's audit
 * trail, newest first, paginated server-side. Metadata stays collapsed so a
 * long trail stays scannable.
 *
 * Maps to: organizations end-to-end design, Slice D (admin org detail).
 */
import { useCallback, useState } from "react";

import { formatTimestamp } from "@/components/modules/admin/admin-money-primitives";
import { humaniseAction } from "@/components/modules/admin/org-detail/org-detail-helpers";
import { EmptyNote, ListRow, PanelError, PanelSkeleton, Section } from "@/components/modules/admin/org-detail/org-detail-states";
import { useAdminOrgResource } from "@/components/modules/admin/org-detail/use-admin-org-resource";
import { Button } from "@/components/ui/button";
import { adminOrgAuditV1AdminOrgsOrgIdAuditGet } from "@/lib/generated/sdk.gen";
import type { AdminOrgAuditResponse } from "@/lib/generated/types.gen";
import { formatLabel } from "@/lib/marketplace/format";

const PAGE_SIZE = 20;

/**
 * Render the audit tab.
 *
 * @param orgId - Organization whose audit trail to list.
 */
export function OrgAuditTab({ orgId }: { orgId: string }) {
  const [page, setPage] = useState(1);
  const load = useCallback(
    (headers: Record<string, string>) =>
      adminOrgAuditV1AdminOrgsOrgIdAuditGet({
        headers,
        path: { org_id: orgId },
        query: { page, page_size: PAGE_SIZE },
      }),
    [orgId, page],
  );
  const { data, error, loading, retry } = useAdminOrgResource<AdminOrgAuditResponse>(load);

  if (loading) return <PanelSkeleton />;
  if (error || !data) return <PanelError message={error ?? "Could not load the audit trail."} onRetry={retry} />;

  const lastPage = Math.max(1, Math.ceil(data.total / data.page_size));
  return (
    <Section aside={`Page ${data.page} of ${lastPage} · ${data.total} entries`} title="Audit trail">
      {data.items.length === 0 ? (
        <EmptyNote>No audit entries.</EmptyNote>
      ) : (
        <ul className="grid gap-2">
          {data.items.map((item) => (
            <ListRow columns="md:grid-cols-[1fr_2fr_1fr_1fr]" key={item.log_id}>
              <p className="break-words font-semibold text-foreground">{item.actor?.display_name ?? "System"}</p>
              <div className="min-w-0">
                <p className="break-words text-sm text-foreground">{humaniseAction(item.action)}</p>
                {Object.keys(item.metadata).length > 0 ? (
                  <details className="text-sm">
                    <summary className="flex min-h-11 cursor-pointer items-center text-foreground-muted">Details</summary>
                    <pre className="overflow-x-auto whitespace-pre-wrap break-all rounded-lg bg-surface-1 p-2 text-xs text-foreground">
                      {JSON.stringify(item.metadata, null, 2)}
                    </pre>
                  </details>
                ) : null}
              </div>
              <p className="break-all text-sm text-foreground-muted">
                {formatLabel(item.target_type)}
                {item.target_id ? ` · ${item.target_id}` : ""}
              </p>
              <p className="text-sm text-foreground-muted">{formatTimestamp(item.created_at)}</p>
            </ListRow>
          ))}
        </ul>
      )}
      <div className="grid grid-cols-2 gap-2 sm:flex sm:justify-end">
        <Button disabled={data.page <= 1} onClick={() => setPage(data.page - 1)} variant="secondary">
          Previous
        </Button>
        <Button disabled={data.page >= lastPage} onClick={() => setPage(data.page + 1)} variant="secondary">
          Next
        </Button>
      </div>
    </Section>
  );
}
