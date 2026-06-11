"use client";

/**
 * Operator licensed Framework library.
 *
 * Lists active licenses and requests short-lived download URLs only after the
 * backend confirms role, KYC, license state, and version coverage.
 */
import { useEffect, useState } from "react";

import {
  downloadLicensedArtifact,
  getExploreFrameworkDetail,
  listOperatorLibrary,
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
import { formatLabel, formatMoney } from "@/lib/marketplace/format";

import { FrameworkReviewPanel } from "./framework-review-panel";

type LibraryCardState = {
  artifacts: ExploreArtifactSummary[];
  error: string | null;
};

/**
 * Render Operator licenses and download actions.
 */
export function OperatorLibrary() {
  const [error, setError] = useState<string | null>(null);
  const [items, setItems] = useState<LibraryItem[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function loadLibrary() {
      configureBrowserClient();
      const result = await listOperatorLibrary({
        headers: getAccessTokenHeaders(),
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
  }, []);

  if (loading) {
    return <p className="text-sm text-foreground-muted">Loading library.</p>;
  }

  if (error) {
    return <p className="text-sm text-error">{error}</p>;
  }

  if (items.length === 0) {
    return (
      <div className="rounded-[8px] border border-border-default bg-surface-2 p-8 text-center">
        <h2 className="font-heading text-xl font-bold text-foreground">
          No licensed frameworks yet
        </h2>
        <p className="mt-2 text-sm text-foreground-muted">
          Purchased and admin-granted frameworks will appear here.
        </p>
      </div>
    );
  }

  return (
    <div className="grid gap-4">
      {items.map((item) => (
        <LibraryCard item={item} key={item.license_id} />
      ))}
    </div>
  );
}

type LibraryCardProps = {
  item: LibraryItem;
};

/**
 * Render one licensed Framework with version-aware download links.
 *
 * @param props - Operator library item.
 */
function LibraryCard({ item }: LibraryCardProps) {
  const [state, setState] = useState<LibraryCardState>({
    artifacts: [],
    error: null,
  });

  useEffect(() => {
    async function loadArtifacts() {
      configureBrowserClient();
      const result = await getExploreFrameworkDetail({
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
    const result = await downloadLicensedArtifact({
      headers: getAccessTokenHeaders(),
      path: {
        artifact_id: artifactId,
        framework_id: item.framework_id,
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
    <article className="rounded-[8px] border border-border-default bg-surface-2 p-5">
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
        <p className="font-semibold text-foreground">
          {formatMoney(item.price, item.currency)}
        </p>
      </div>
      <div className="mt-4 grid gap-3 text-sm text-foreground-muted sm:grid-cols-3">
        <span>Status {formatLabel(item.status)}</span>
        <span>
          Seats {item.seats_used}
          {item.seats_total ? ` / ${item.seats_total}` : ""}
        </span>
        <span>
          Expires {item.expires_at ? new Date(item.expires_at).toLocaleDateString() : "Never"}
        </span>
      </div>
      {state.error ? <p className="mt-3 text-sm text-error">{state.error}</p> : null}
      <div className="mt-5 grid gap-2">
        {state.artifacts.map((artifact) => (
          <button
            className="flex min-h-11 items-center justify-between gap-4 rounded-[6px] border border-border-default bg-background px-3 py-2 text-left text-sm text-foreground hover:bg-surface-3"
            key={artifact.id}
            onClick={() => handleDownload(artifact.id)}
            type="button"
          >
            <span>{artifact.name}</span>
            <span className="font-semibold text-accent">Download</span>
          </button>
        ))}
      </div>
      <FrameworkReviewPanel frameworkId={item.framework_id} />
    </article>
  );
}
