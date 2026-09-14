"use client";

/**
 * One licensed Framework in an organization's shared library.
 *
 * Active licenses list their artifacts as download actions, and org admins
 * also get review and license-grant controls. Expired and revoked licenses
 * keep their status pill but offer no download or grant: the API refuses
 * downloads for them, so the card says the license is no longer active
 * instead of presenting actions that would fail.
 *
 * Maps to: docs/superpowers/specs/2026-09-14-organizations-end-to-end-design.md §Slice C.
 */
import { useEffect, useState } from "react";

import {
  getExploreFrameworkDetail,
  requestOrgLibraryArtifactDownload,
} from "@/lib/generated/sdk.gen";
import type {
  ExploreArtifactSummary,
  LibraryItem,
} from "@/lib/generated/types.gen";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import { StatusPill } from "@/components/ui/status-pill";
import { formatLabel, formatMoney, formatShortDate } from "@/lib/marketplace/format";

import { FrameworkReviewPanel } from "./framework-review-panel";
import { OrgLicenseGrantPanel } from "./org-license-grant-panel";

/** How a license reached the org's library, in plain words. */
const SOURCE_LABELS: Record<string, string> = {
  purchase: "Purchased",
  collection: "Collection",
};

/** License type names as the pricing page words them. */
const LICENSE_TYPE_LABELS: Record<string, string> = {
  single_user: "Single user",
  team: "Team",
  organizational: "Organization",
};

/**
 * Describe when a license lapses, or when it lapsed.
 *
 * @param item - Library item carrying `status` and `expires_at`.
 */
function describeLicenseExpiry(item: Pick<LibraryItem, "status" | "expires_at">): string {
  if (!item.expires_at) return "No expiry";
  const date = formatShortDate(item.expires_at);
  return item.status === "expired" ? `Expired ${date}` : `Expires ${date}`;
}

type LibraryCardState = {
  artifacts: ExploreArtifactSummary[];
  error: string | null;
};

export type LibraryCardProps = {
  /** Whether the caller is an org admin or owner (sees price and management). */
  canManage: boolean;
  item: LibraryItem;
  orgId: string;
};

/**
 * Render one licensed Framework with version-aware download links for an org.
 *
 * @param props - Org library item, orgId, and whether the caller manages it.
 */
export function LibraryCard({ canManage, item, orgId }: LibraryCardProps) {
  const isActive = item.status === "active";
  const [state, setState] = useState<LibraryCardState>({
    artifacts: [],
    error: null,
  });

  useEffect(() => {
    // An inactive license cannot download, so its artifact list is not needed.
    if (!isActive) return;
    async function loadArtifacts() {
      configureBrowserClient();
      const result = await getExploreFrameworkDetail({
        headers: getAccessTokenHeaders(),
        path: { framework_id: item.framework_id },
      });
      if (!result.response.ok || !result.data) {
        setState((current) => ({
          ...current,
          error: "Artifact list is unavailable.",
        }));
        return;
      }
      setState({ artifacts: result.data.artifacts, error: null });
    }

    void loadArtifacts();
  }, [isActive, item.framework_id]);

  async function handleDownload(artifactId: string) {
    configureBrowserClient();
    const result = await requestOrgLibraryArtifactDownload({
      headers: getAccessTokenHeaders(),
      path: {
        org_id: orgId,
        license_id: item.license_id,
        artifact_id: artifactId,
      },
    });

    if (!result.response.ok || !result.data) {
      setState((current) => ({
        ...current,
        error: describeGeneratedError(result.error),
      }));
      return;
    }

    window.location.assign(result.data.download_url);
  }

  return (
    <article className="rounded-2xl border border-border-default bg-surface-2 p-5 shadow-sm">
      <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
            {LICENSE_TYPE_LABELS[item.license_type] ?? formatLabel(item.license_type)} license
          </p>
          <h2 className="mt-1 font-heading text-xl font-bold text-foreground">
            {item.title}
          </h2>
          <p className="mt-2 text-sm text-foreground-muted">
            Licensed version {item.version_at_grant}. Current version{" "}
            {item.current_version}.
          </p>
        </div>
        {canManage ? (
          <p className="font-semibold text-foreground">
            {formatMoney(item.price, item.currency)}
          </p>
        ) : null}
      </div>
      <div className="mt-4 flex flex-wrap items-center gap-2 text-sm text-foreground-muted">
        <StatusPill status={item.status} />
        <span className="inline-flex items-center rounded-badge border border-border-default bg-surface-1 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.05em] text-foreground-muted">
          {SOURCE_LABELS[item.source] ?? formatLabel(item.source)}
        </span>
        <span>
          Seats {item.seats_used}
          {item.seats_total ? ` / ${item.seats_total}` : ""}
        </span>
        <span>{describeLicenseExpiry(item)}</span>
      </div>
      {state.error ? <p className="mt-3 text-sm text-error">{state.error}</p> : null}
      {!isActive ? (
        <p className="mt-3 text-sm text-foreground-muted">This license is no longer active.</p>
      ) : null}
      <div className="mt-5 grid gap-2">
        {state.artifacts.map((artifact) => (
          <button
            className="flex min-h-12 items-center justify-between gap-4 rounded-xl border border-border-default bg-background px-3 py-2 text-left text-sm text-foreground hover:bg-surface-3"
            key={artifact.id}
            onClick={() => handleDownload(artifact.id)}
            type="button"
          >
            <span>{artifact.name}</span>
            <span className="font-semibold text-accent">Download</span>
          </button>
        ))}
      </div>
      {canManage ? (
        <>
          <FrameworkReviewPanel frameworkId={item.framework_id} />
          {isActive ? (
            <OrgLicenseGrantPanel orgId={orgId} licenseId={item.license_id} />
          ) : null}
        </>
      ) : null}
    </article>
  );
}
