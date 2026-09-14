"use client";

/**
 * Attestations tab of the admin organization detail page: Attestations the
 * organization is working on, with the admin reading of each status, the
 * reviewing member and the completion due date.
 *
 * Maps to: organizations end-to-end design, Slice D (admin org detail).
 */
import { useCallback } from "react";

import { EmptyNote, ListRow, PanelError, PanelSkeleton, Section } from "@/components/modules/admin/org-detail/org-detail-states";
import { useAdminOrgResource } from "@/components/modules/admin/org-detail/use-admin-org-resource";
import { StatusPill, attestationStatusKey } from "@/components/ui/status-pill";
import { adminOrgAttestationsV1AdminOrgsOrgIdAttestationsGet } from "@/lib/generated/sdk.gen";
import type { AdminOrgAttestationsResponse } from "@/lib/generated/types.gen";
import { formatShortDate } from "@/lib/marketplace/format";

/**
 * Render the attestations tab.
 *
 * @param orgId - Organization whose attestations to list.
 */
export function OrgAttestationsTab({ orgId }: { orgId: string }) {
  const load = useCallback(
    (headers: Record<string, string>) =>
      adminOrgAttestationsV1AdminOrgsOrgIdAttestationsGet({ headers, path: { org_id: orgId } }),
    [orgId],
  );
  const { data, error, loading, retry } = useAdminOrgResource<AdminOrgAttestationsResponse>(load);

  if (loading) return <PanelSkeleton />;
  if (error || !data) return <PanelError message={error ?? "Could not load attestations."} onRetry={retry} />;

  return (
    <Section
      aside={`${data.counts.in_flight} in flight · ${data.counts.completed} completed`}
      title="Attestations in flight"
    >
      {data.attestations.length === 0 ? (
        <EmptyNote>No attestations in flight.</EmptyNote>
      ) : (
        <ul className="grid gap-2">
          {data.attestations.map((attestation) => (
            <ListRow columns="md:grid-cols-[2fr_auto_1fr_1fr]" key={attestation.id}>
              <p className="break-words font-semibold text-foreground">
                {attestation.target_title ?? "Untitled target"}
              </p>
              <StatusPill className="w-fit" status={attestationStatusKey(attestation.status, "admin")} />
              <p className="break-words text-sm text-foreground-muted">
                {attestation.reviewing_member_display_name ?? "No reviewer yet"}
              </p>
              <p className="text-sm text-foreground-muted">
                Due {formatShortDate(attestation.completion_due_at, "not set")}
              </p>
            </ListRow>
          ))}
        </ul>
      )}
    </Section>
  );
}
