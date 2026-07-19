"use client";

/**
 * Org Operator licensed Framework library.
 *
 * Lists active licenses available to the organization and requests short-lived
 * download URLs for artifacts using the org operator capability.
 */
import { useEffect, useState } from "react";

import {
  getExploreFrameworkDetail,
  listOrgLibrary,
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
import { CardSkeleton } from "@/components/ui/skeletons/card-skeleton";
import { formatLabel, formatMoney } from "@/lib/marketplace/format";
import { useOrganization } from "@/components/modules/organizations/organization-context";

import { FrameworkReviewPanel } from "./framework-review-panel";
import { OrgLicenseGrantPanel } from "./org-license-grant-panel";

type LibraryCardState = {
  artifacts: ExploreArtifactSummary[];
  error: string | null;
};

type OrgOperatorLibraryProps = {
  orgId: string;
};

/**
 * Render Org Operator licenses and download actions.
 */
export function OrgOperatorLibrary({ orgId }: OrgOperatorLibraryProps) {
  const { role } = useOrganization();
  const canManage = role === "admin" || role === "owner";
  const [error, setError] = useState<string | null>(null);
  const [items, setItems] = useState<LibraryItem[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function loadLibrary() {
      configureBrowserClient();
      const result = await listOrgLibrary({
        headers: getAccessTokenHeaders(),
        path: { org_id: orgId },
        query: { page: 1, page_size: 25 },
      });
      if (!result.response.ok || !result.data) {
        setError(describeGeneratedError(result.error));
        setLoading(false);
        return;
      }
      setItems(result.data.items);
      setLoading(false);
    }

    void loadLibrary();
  }, [orgId]);

  if (loading) {
    return <CardSkeleton />;
  }

  if (error) {
    return <p className="text-sm text-error">{error}</p>;
  }

  if (items.length === 0) {
    return (
      <div className="rounded-2xl border border-border-default bg-surface-2 p-8 text-center shadow-sm">
        <h2 className="font-heading text-xl font-bold text-foreground">
          No licensed frameworks yet
        </h2>
        <p className="mt-2 text-sm text-foreground-muted">
          Purchased frameworks for this organization will appear here.
        </p>
      </div>
    );
  }

  return (
    <div className="grid gap-4">
      {items.map((item) => (
        <LibraryCard
          canManage={canManage}
          item={item}
          orgId={orgId}
          key={item.license_id}
        />
      ))}
    </div>
  );
}

type LibraryCardProps = {
  canManage: boolean;
  item: LibraryItem;
  orgId: string;
};

/**
 * Render one licensed Framework with version-aware download links for an org.
 *
 * @param props - Org library item and orgId.
 */
function LibraryCard({ canManage, item, orgId }: LibraryCardProps) {
  const [state, setState] = useState<LibraryCardState>({
    artifacts: [],
    error: null,
  });

  useEffect(() => {
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
  }, [item.framework_id]);

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
            {formatLabel(item.license_type)} license
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
      <div className="mt-4 grid gap-3 text-sm text-foreground-muted sm:grid-cols-3">
        <span>Status {formatLabel(item.status)}</span>
        <span>
          Source{" "}
          {item.source === "collection" ? "Collection" : formatLabel(item.source)}
        </span>
        <span>
          Seats {item.seats_used}
          {item.seats_total ? ` / ${item.seats_total}` : ""}
        </span>
        <span className="sm:col-span-3">
          Expires {item.expires_at ? new Date(item.expires_at).toLocaleDateString() : "Never"}
        </span>
      </div>
      {state.error ? <p className="mt-3 text-sm text-error">{state.error}</p> : null}
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
          <OrgLicenseGrantPanel orgId={orgId} licenseId={item.license_id} />
        </>
      ) : null}
    </article>
  );
}
