"use client";

/**
 * Frameworks tab of the admin organization detail page: Frameworks the
 * organization owns (linking to Explore only once published, since other
 * statuses are not publicly reachable) and the Licenses it holds.
 *
 * Maps to: organizations end-to-end design, Slice D (admin org detail).
 */
import Link from "next/link";
import { useCallback } from "react";

import { EmptyNote, ListRow, PanelError, PanelSkeleton, Section } from "@/components/modules/admin/org-detail/org-detail-states";
import { useAdminOrgResource } from "@/components/modules/admin/org-detail/use-admin-org-resource";
import { StatusPill } from "@/components/ui/status-pill";
import { adminOrgFrameworksV1AdminOrgsOrgIdFrameworksGet } from "@/lib/generated/sdk.gen";
import type { AdminOrgFrameworksResponse } from "@/lib/generated/types.gen";
import { formatLabel, formatShortDate } from "@/lib/marketplace/format";

/**
 * Render the frameworks and licenses tab.
 *
 * @param orgId - Organization whose frameworks and licenses to list.
 */
export function OrgFrameworksTab({ orgId }: { orgId: string }) {
  const load = useCallback(
    (headers: Record<string, string>) =>
      adminOrgFrameworksV1AdminOrgsOrgIdFrameworksGet({ headers, path: { org_id: orgId } }),
    [orgId],
  );
  const { data, error, loading, retry } = useAdminOrgResource<AdminOrgFrameworksResponse>(load);

  if (loading) return <PanelSkeleton />;
  if (error || !data) return <PanelError message={error ?? "Could not load frameworks."} onRetry={retry} />;

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Section title={`Frameworks (${data.frameworks.length})`}>
        {data.frameworks.length === 0 ? (
          <EmptyNote>No frameworks owned.</EmptyNote>
        ) : (
          <ul className="grid gap-2">
            {data.frameworks.map((framework) => (
              <ListRow columns="md:grid-cols-[1fr_auto_auto]" key={framework.id}>
                {framework.status === "published" ? (
                  <Link
                    className="inline-flex min-h-11 items-center break-words font-semibold text-accent underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
                    href={`/explore/${framework.id}`}
                  >
                    {framework.title}
                  </Link>
                ) : (
                  <p className="break-words font-semibold text-foreground">{framework.title}</p>
                )}
                <StatusPill className="w-fit" status={framework.status} />
                <p className="text-sm text-foreground-muted">{formatShortDate(framework.created_at)}</p>
              </ListRow>
            ))}
          </ul>
        )}
      </Section>
      <Section title={`Licenses held (${data.licenses.length})`}>
        {data.licenses.length === 0 ? (
          <EmptyNote>No licenses held.</EmptyNote>
        ) : (
          <ul className="grid gap-2">
            {data.licenses.map((license) => (
              <ListRow columns="md:grid-cols-[1fr_auto_auto]" key={license.license_id}>
                <div className="min-w-0">
                  <p className="break-words font-semibold text-foreground">{license.framework_title}</p>
                  <p className="text-sm text-foreground-muted">
                    {formatLabel(license.license_type)} · {license.grant_count}{" "}
                    {license.grant_count === 1 ? "grant" : "grants"}
                  </p>
                </div>
                <StatusPill className="w-fit" status={license.status} />
                <p className="text-sm text-foreground-muted">{formatShortDate(license.created_at)}</p>
              </ListRow>
            ))}
          </ul>
        )}
      </Section>
    </div>
  );
}
