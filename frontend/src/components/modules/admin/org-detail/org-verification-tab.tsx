"use client";

/**
 * Verification tab of the admin organization detail page: the legal profile
 * the organization submitted for business verification (KYB), review notes,
 * and its documents behind short-lived presigned links. Opening a document is
 * audited server-side when the links are minted, so the page says so.
 *
 * Maps to: organizations end-to-end design, Slice D (admin org detail).
 */
import { useCallback } from "react";

import { EmptyNote, Fact, ListRow, PanelError, PanelSkeleton, Section } from "@/components/modules/admin/org-detail/org-detail-states";
import { useAdminOrgResource } from "@/components/modules/admin/org-detail/use-admin-org-resource";
import { StatusPill, ownerStatusKey } from "@/components/ui/status-pill";
import { adminOrgVerificationV1AdminOrgsOrgIdVerificationGet } from "@/lib/generated/sdk.gen";
import type { AdminOrgVerificationResponse } from "@/lib/generated/types.gen";
import { formatLabel, formatShortDate } from "@/lib/marketplace/format";
import { taxDocumentLabel } from "@/lib/organizations/tax-documents";

/**
 * Join the string parts of a submitted address into one line.
 *
 * @param address - Free-form address object from the API.
 */
function formatAddress(address: Record<string, unknown> | null): string {
  if (!address) return "";
  return Object.values(address)
    .filter((part): part is string => typeof part === "string" && part.trim() !== "")
    .join(", ");
}

/**
 * Render the verification tab.
 *
 * @param orgId - Organization whose verification record to show.
 */
export function OrgVerificationTab({ orgId }: { orgId: string }) {
  const load = useCallback(
    (headers: Record<string, string>) =>
      adminOrgVerificationV1AdminOrgsOrgIdVerificationGet({ headers, path: { org_id: orgId } }),
    [orgId],
  );
  const { data, error, loading, retry } = useAdminOrgResource<AdminOrgVerificationResponse>(load);

  if (loading) return <PanelSkeleton />;
  if (error || !data) return <PanelError message={error ?? "Could not load verification."} onRetry={retry} />;

  return (
    <div className="grid gap-4">
      <Section aside={<StatusPill status={ownerStatusKey(data.kyb_status, "kyb")} />} title="Legal profile">
        <dl className="grid gap-2 md:grid-cols-2">
          <Fact label="Legal name">{data.legal_name}</Fact>
          <Fact label="Registration number">{data.registration_number}</Fact>
          <Fact label="Address">{formatAddress(data.address)}</Fact>
          <Fact label="Tax document">{taxDocumentLabel(data.tax_document_type)}</Fact>
          <Fact label="Submitted">{formatShortDate(data.kyb_submitted_at)}</Fact>
          <Fact label="Verified">{formatShortDate(data.kyb_verified_at)}</Fact>
        </dl>
        {data.kyb_review_notes ? (
          <p className="break-words rounded-xl border border-border-default bg-surface-2 p-3 text-sm text-foreground">
            <span className="font-semibold">Review notes:</span> {data.kyb_review_notes}
          </p>
        ) : null}
      </Section>
      <Section title="Documents">
        <p className="text-sm text-foreground-muted">
          Links expire after 5 minutes. Opening documents is recorded in the audit log.
        </p>
        {data.documents.length === 0 ? (
          <EmptyNote>No documents submitted.</EmptyNote>
        ) : (
          <ul className="grid gap-2">
            {data.documents.map((doc) => (
              <ListRow columns="md:grid-cols-[1fr_auto]" key={`${doc.kind}-${doc.file_name}`}>
                <div className="min-w-0">
                  <p className="font-semibold text-foreground">{formatLabel(doc.kind)}</p>
                  <p className="break-all text-sm text-foreground-muted">{doc.file_name}</p>
                </div>
                {doc.download_url ? (
                  <a
                    aria-label={`Open ${doc.file_name}`}
                    className="inline-flex min-h-11 items-center justify-center rounded-xl border border-border-default bg-surface-1 px-4 text-sm font-semibold text-foreground hover:bg-surface-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
                    href={doc.download_url}
                    rel="noopener noreferrer"
                    target="_blank"
                  >
                    Open
                  </a>
                ) : (
                  <span className="text-sm text-foreground-muted">Not uploaded</span>
                )}
              </ListRow>
            ))}
          </ul>
        )}
      </Section>
    </div>
  );
}
