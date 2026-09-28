"use client";

/**
 * Admin Framework detail.
 *
 * A Framework held by the processing pipeline is `pipeline_failed`: it is not
 * published, so it appears in neither the admin Framework directory (published
 * only) nor the suspended list. The moderation queue names it but shows
 * nothing of the Framework itself, so before this page the only way an admin
 * could inspect a held Framework was the database.
 *
 * Read-only and metadata-only by design. The API returns no file key and no
 * download URL, so an admin adjudicates a hold from the findings — a held
 * Artifact's contents stay behind the same licence gate as any other.
 *
 * Maps to: FR-ADMIN (content moderation), FR-FWK-019 (artifact processing).
 */
import { ArrowLeftIcon } from "@radix-ui/react-icons";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { StatusPill } from "@/components/ui/status-pill";
import { TableSkeleton } from "@/components/ui/skeletons/table-skeleton";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import { getAdminFrameworkDetailV1AdminFrameworksFrameworkIdGet } from "@/lib/generated/sdk.gen";
import type { AdminFrameworkDetailResponse } from "@/lib/generated/types.gen";
import {
  formatFileSize,
  formatLabel,
  formatMoney,
  formatShortDate,
} from "@/lib/marketplace/format";

type AdminFrameworkDetailProps = {
  /** UUID of the Framework to display. */
  frameworkId: string;
};

type Artifact = AdminFrameworkDetailResponse["artifacts"][number];

/**
 * Name whichever seller owns the Framework.
 *
 * Exactly one of the two is set (`ck_frameworks_seller_xor`), so this never
 * has to merge them.
 *
 * @param detail - The loaded Framework detail.
 */
function ownerName(detail: AdminFrameworkDetailResponse): string {
  return detail.organization_name ?? detail.contributor_name ?? "Unknown owner";
}

/**
 * One label/value pair inside a bento card.
 */
function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs uppercase tracking-[0.05em] text-foreground-subtle">
        {label}
      </dt>
      <dd className="mt-1 break-words text-sm text-foreground">{value}</dd>
    </div>
  );
}

/**
 * Explain who clears a hold and how, for the Artifact blocking publication.
 *
 * An admin has no button for a PII review: the redaction is accepted or
 * removed by the Framework's owner. Saying so in place stops an admin hunting
 * for a control that does not exist.
 *
 * @param detail - The loaded Framework detail.
 * @param blocking - Artifacts named in `pipeline_failure_reasons`.
 */
function HoldExplainer({
  detail,
  blocking,
}: {
  detail: AdminFrameworkDetailResponse;
  blocking: Artifact[];
}) {
  if (detail.status !== "pipeline_failed" || blocking.length === 0) {
    return null;
  }
  const owner = ownerName(detail);
  const piiHold = blocking.some((artifact) => artifact.pii_review_needed);
  return (
    <div className="rounded-2xl border border-warning/30 bg-warning/10 p-4 md:p-6">
      <h2 className="font-heading text-base font-semibold text-foreground">
        This Framework cannot publish
      </h2>
      <p className="mt-2 text-sm leading-relaxed text-foreground">
        {piiHold
          ? `Held for PII review. Only the owner can clear it: ${owner} accepts or removes the redaction on the Artifact below.`
          : `Held by the processing pipeline. ${owner} must replace or resubmit the Artifact below.`}
      </p>
    </div>
  );
}

/**
 * One Artifact row: processing state and findings, never the file.
 *
 * @param artifact - Artifact metadata from the admin detail response.
 */
function ArtifactRow({ artifact }: { artifact: Artifact }) {
  return (
    <li className="rounded-xl border border-border-default bg-surface-2 p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="break-words text-sm font-medium text-foreground">
            {artifact.name}
          </p>
          <p className="mt-0.5 text-xs text-foreground-subtle">
            {formatFileSize(artifact.file_size)} · {artifact.mime_type}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {artifact.blocking ? (
            <span className="inline-flex items-center rounded-badge border border-error/30 bg-error/10 px-2 py-0.5 text-xs font-medium uppercase tracking-[0.05em] text-error">
              Blocking
            </span>
          ) : null}
          <StatusPill status={artifact.processing_status} />
        </div>
      </div>

      {artifact.pii_types_found.length > 0 ? (
        <p className="mt-3 text-sm text-foreground">
          <span className="text-foreground-subtle">PII found: </span>
          {artifact.pii_types_found.map((type) => formatLabel(type)).join(", ")}
        </p>
      ) : null}

      {artifact.redaction_status ? (
        <p className="mt-1 text-sm text-foreground-muted">
          Redaction {artifact.redaction_status}
          {artifact.redaction_accepted ? ", accepted by the owner" : ", not yet accepted"}
        </p>
      ) : null}

      {artifact.rarity_score !== null && artifact.rarity_score !== undefined ? (
        <p className="mt-1 text-sm text-foreground-muted">
          Rarity {artifact.rarity_score}
        </p>
      ) : null}
    </li>
  );
}

/**
 * Render one Framework for admin review, in any status.
 *
 * @param frameworkId - UUID of the Framework to load.
 */
export function AdminFrameworkDetail({ frameworkId }: AdminFrameworkDetailProps) {
  const [detail, setDetail] = useState<AdminFrameworkDetailResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    configureBrowserClient();
    const result = await getAdminFrameworkDetailV1AdminFrameworksFrameworkIdGet({
      headers: getAccessTokenHeaders(),
      path: { framework_id: frameworkId },
    });
    setLoading(false);
    if (!result.response.ok || !result.data) {
      setError(describeGeneratedError(result.error));
      return;
    }
    setError(null);
    setDetail(result.data);
  }, [frameworkId]);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) {
    return <TableSkeleton />;
  }

  if (error !== null || detail === null) {
    return (
      <div className="rounded-2xl border border-border-default bg-surface-1 p-4 md:p-6">
        <p className="text-sm text-error">{error ?? "Could not load this Framework."}</p>
      </div>
    );
  }

  const blocking = detail.artifacts.filter((artifact) => artifact.blocking);

  return (
    <div className="space-y-4 md:space-y-6">
      <Link
        href="/admin/moderation"
        className="-ml-1 inline-flex min-h-12 items-center gap-1.5 px-1 text-sm font-semibold text-accent transition-colors hover:text-accent/80 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent"
      >
        <ArrowLeftIcon className="h-4 w-4" aria-hidden="true" />
        Moderation
      </Link>

      <header className="rounded-2xl border border-border-default bg-surface-1 p-4 shadow-sm md:p-6">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h1 className="font-heading text-xl font-semibold tracking-[-0.02em] text-foreground md:text-2xl">
              {detail.title}
            </h1>
            <p className="mt-1 text-sm text-foreground-subtle">
              Version {detail.version} · {formatLabel(detail.category)}
            </p>
          </div>
          <StatusPill status={detail.status} />
        </div>
        <p className="mt-4 whitespace-pre-line text-sm leading-relaxed text-foreground-muted">
          {detail.description}
        </p>
      </header>

      <HoldExplainer detail={detail} blocking={blocking} />

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 md:gap-6">
        <section className="rounded-2xl border border-border-default bg-surface-1 p-4 shadow-sm md:p-6">
          <h2 className="font-heading text-base font-semibold text-foreground">Owner</h2>
          <dl className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Field label="Seller" value={ownerName(detail)} />
            <Field
              label="Sells as"
              value={detail.organization_id ? "Organization" : "Contributor"}
            />
            {detail.contributor_email ? (
              <Field label="Contact" value={detail.contributor_email} />
            ) : null}
          </dl>
        </section>

        <section className="rounded-2xl border border-border-default bg-surface-1 p-4 shadow-sm md:p-6">
          <h2 className="font-heading text-base font-semibold text-foreground">Listing</h2>
          <dl className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Field label="Price" value={formatMoney(detail.price, detail.currency)} />
            <Field label="Sector" value={formatLabel(detail.sector)} />
            <Field label="Created" value={formatShortDate(detail.created_at)} />
            <Field
              label="Published"
              value={detail.published_at ? formatShortDate(detail.published_at) : "Never"}
            />
          </dl>
        </section>
      </div>

      <section className="rounded-2xl border border-border-default bg-surface-1 p-4 shadow-sm md:p-6">
        <h2 className="font-heading text-base font-semibold text-foreground">
          Artifacts ({detail.artifacts.length})
        </h2>
        {detail.artifacts.length === 0 ? (
          <p className="mt-4 text-sm text-foreground-muted">
            This Framework has no Artifacts.
          </p>
        ) : (
          <ul className="mt-4 space-y-3">
            {detail.artifacts.map((artifact) => (
              <ArtifactRow key={artifact.artifact_id} artifact={artifact} />
            ))}
          </ul>
        )}
      </section>

      <section className="rounded-2xl border border-border-default bg-surface-1 p-4 shadow-sm md:p-6">
        <h2 className="font-heading text-base font-semibold text-foreground">History</h2>
        {detail.timeline.length === 0 ? (
          <p className="mt-4 text-sm text-foreground-muted">
            Nothing has been recorded against this Framework yet.
          </p>
        ) : (
          <ul className="mt-4 space-y-3">
            {detail.timeline.map((entry, index) => (
              <li
                key={`${entry.action}-${entry.created_at}-${index}`}
                className="rounded-xl border border-border-default bg-surface-2 p-4"
              >
                <p className="text-sm font-medium text-foreground">
                  {formatLabel(entry.action)}
                </p>
                <p className="mt-0.5 text-xs text-foreground-subtle">
                  {entry.actor_name ? `by ${entry.actor_name} · ` : ""}
                  {formatShortDate(entry.created_at)}
                </p>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
