"use client";

/**
 * Contributor Framework edit workspace.
 *
 * Loads Framework metadata and artifacts, then composes the smaller action
 * components that call generated backend endpoints.
 */
import { useCallback, useEffect, useState } from "react";
import { TableSkeleton } from "@/components/ui/skeletons/table-skeleton";

import { ArtifactUploader } from "@/components/modules/frameworks/artifact-uploader";
import { DelistButton } from "@/components/modules/frameworks/delist-button";
import { FrameworkForm } from "@/components/modules/frameworks/framework-form";
import { PiiReviewResolution } from "@/components/modules/frameworks/pii-review-resolution";
import { PipelineStatusPanel } from "@/components/modules/frameworks/pipeline-status-panel";
import { PublishButton } from "@/components/modules/frameworks/publish-button";
import { SoftFailAcknowledgement } from "@/components/modules/frameworks/soft-fail-acknowledgement";
import { VersionRadios } from "@/components/modules/frameworks/version-radios";
import {
  createFrameworkVersion,
  deleteArtifact,
  getContributorFramework,
  listFrameworkArtifacts,
  submitFramework,
  updateFramework,
} from "@/lib/generated/sdk.gen";
import type {
  ArtifactResponse,
  FrameworkCreate,
  FrameworkResponse,
} from "@/lib/generated/types.gen";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import {
  formatFileSize,
  formatFrameworkStatus,
} from "@/lib/marketplace/format";

type FrameworkEditorProps = {
  frameworkId: string;
};

/**
 * Render the Contributor Framework edit screen.
 *
 * @param props - Framework id from the route.
 */
export function FrameworkEditor({ frameworkId }: FrameworkEditorProps) {
  const [artifacts, setArtifacts] = useState<ArtifactResponse[]>([]);
  const [changeType, setChangeType] = useState<"fix" | "improvement" | "major">(
    "improvement",
  );
  const [changeLog, setChangeLog] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [framework, setFramework] = useState<FrameworkResponse | null>(null);
  const [loading, setLoading] = useState(true);

  // Reload framework + artifacts. `quiet` skips the loading skeleton so the
  // background poll never flashes the spinner over a populated workspace.
  const loadWorkspace = useCallback(
    async (quiet = false) => {
      configureBrowserClient();
      if (!quiet) {
        setLoading(true);
      }
      const [frameworkResult, artifactsResult] = await Promise.all([
        getContributorFramework({
          headers: getAccessTokenHeaders(),
          path: { framework_id: frameworkId },
        }),
        listFrameworkArtifacts({
          headers: getAccessTokenHeaders(),
          path: { framework_id: frameworkId },
        }),
      ]);

      if (!frameworkResult.response.ok || !frameworkResult.data) {
        if (!quiet) {
          setError(describeGeneratedError(frameworkResult.error));
          setLoading(false);
        }
        return;
      }

      setFramework(frameworkResult.data);
      setArtifacts(artifactsResult.data ?? []);
      if (!quiet) {
        setLoading(false);
      }
    },
    [frameworkId],
  );

  useEffect(() => {
    void loadWorkspace();
  }, [loadWorkspace]);

  // The processing pipeline runs in a Celery worker; the artifact/framework
  // status flips server-side seconds after upload. Poll while anything is
  // in flight so the UI reflects flagged_pii / pipeline_failed / processed
  // without forcing the Contributor to hard-reload.
  const isPipelineActive =
    framework !== null &&
    (framework.status === "processing" ||
      framework.status === "submitted" ||
      artifacts.some(
        (artifact) =>
          artifact.processing_status === "pending" ||
          artifact.processing_status === "processing",
      ));

  useEffect(() => {
    if (!isPipelineActive) {
      return;
    }
    const intervalId = setInterval(() => {
      void loadWorkspace(true);
    }, 3000);
    return () => clearInterval(intervalId);
  }, [isPipelineActive, loadWorkspace]);

  async function handleUpdate(payload: FrameworkCreate) {
    configureBrowserClient();
    const result = await updateFramework({
      body: payload,
      headers: getAccessTokenHeaders(),
      path: { framework_id: frameworkId },
    });
    if (!result.response.ok || !result.data) {
      throw new Error(describeGeneratedError(result.error));
    }
    setFramework(result.data);
  }

  async function handleSubmitGate() {
    configureBrowserClient();
    const result = await submitFramework({
      headers: getAccessTokenHeaders(),
      path: { framework_id: frameworkId },
    });
    if (!result.response.ok || !result.data) {
      setError(describeGeneratedError(result.error));
      return;
    }
    setFramework(result.data);
  }

  async function handleCreateVersion() {
    configureBrowserClient();
    const result = await createFrameworkVersion({
      body: {
        artifact_inheritance: Object.fromEntries(
          artifacts.map((artifact) => [artifact.id, true]),
        ),
        change_log:
          changeLog.trim() ||
          "Contributor draft version created from dashboard.",
        change_type: changeType,
      },
      headers: getAccessTokenHeaders(),
      path: { framework_id: frameworkId },
    });
    if (!result.response.ok || !result.data) {
      setError(describeGeneratedError(result.error));
      return;
    }
    setFramework(result.data);
  }

  async function handleRemoveArtifact(artifactId: string) {
    configureBrowserClient();
    const result = await deleteArtifact({
      headers: getAccessTokenHeaders(),
      path: { artifact_id: artifactId, framework_id: frameworkId },
    });
    if (!result.response.ok) {
      setError(describeGeneratedError(result.error));
      return;
    }
    setArtifacts((current) =>
      current.filter((artifact) => artifact.id !== artifactId),
    );
  }

  if (loading) {
    return <TableSkeleton />;
  }

  if (error || !framework) {
    return <p className="text-sm text-error">{error ?? "Framework not found."}</p>;
  }

  const hasRaritySoftFail = artifacts.some(
    (artifact) => artifact.processing_status === "flagged_rarity",
  );
  const canPublish = framework.status === "pipeline_passed";

  return (
    <div className="grid gap-6 xl:grid-cols-[1fr_380px]">
      <section className="rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm">
        <div className="mb-5 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
              {formatFrameworkStatus(framework.status)}
            </p>
            <h1 className="font-heading text-2xl font-bold text-foreground">
              {framework.title}
            </h1>
          </div>
          <p className="text-sm text-foreground-muted">Version {framework.version}</p>
        </div>
        <FrameworkForm
          framework={framework}
          onSubmit={handleUpdate}
          submitLabel="Save changes"
          leftActions={
            framework.status === "published" ? (
              <DelistButton frameworkId={framework.id} />
            ) : null
          }
        >
          {(framework.status === "draft" || framework.status === "pipeline_failed") && (
            <button
              className="inline-flex min-h-12 items-center justify-center rounded-xl bg-foreground px-6 py-2 text-sm font-semibold text-background shadow-sm outline-none transition-all hover:bg-foreground/90 focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-60 disabled:cursor-not-allowed"
              // Nothing to submit without an artifact, and submitting mid-scan
              // would just re-pick the in-flight job — gate on both.
              disabled={artifacts.length === 0 || isPipelineActive}
              onClick={handleSubmitGate}
              type="button"
            >
              Submit for publishing
            </button>
          )}
          {framework.status === "pipeline_passed" && (
            <PublishButton frameworkId={framework.id} />
          )}
        </FrameworkForm>
      </section>
      <aside className="grid gap-4">
        <ArtifactUploader
          artifactCount={artifacts.length}
          existingBytes={artifacts.reduce(
            (total, artifact) => total + artifact.file_size,
            0,
          )}
          frameworkId={framework.id}
          onUploaded={(artifact) =>
            setArtifacts((current) => [artifact, ...current])
          }
        />
        <ArtifactManifest
          artifacts={artifacts}
          canRemove={
            framework.status === "draft" ||
            framework.status === "pipeline_failed"
          }
          onRemove={handleRemoveArtifact}
        />
        <PipelineStatusPanel
          artifacts={artifacts}
          frameworkId={framework.id}
          frameworkStatus={framework.status}
        />
        <PiiReviewResolution artifacts={artifacts} frameworkId={framework.id} />
        {hasRaritySoftFail ? (
          <SoftFailAcknowledgement frameworkId={framework.id} />
        ) : null}
        {/* Versioning only applies once a Framework is live; a never-published
            draft is edited in place, so the new-version action stays hidden. */}
        {framework.status === "published" ? (
          <section className="rounded-2xl border border-border-default bg-surface-2 p-5 shadow-sm">
            <h2 className="font-heading text-lg font-bold text-foreground">
              New version
            </h2>
            <p className="mt-1 text-sm text-foreground-muted">
              Start a draft revision. The current version stays published until
              the new one passes the pipeline.
            </p>
            <div className="mt-4">
              <VersionRadios onChange={setChangeType} value={changeType} />
            </div>
            <label className="mt-4 block">
              <span className="mb-1.5 block text-sm font-semibold text-foreground">
                Change log
              </span>
              <textarea
                className="min-h-20 w-full rounded-xl border border-border-default bg-background px-3 py-2 text-sm text-foreground outline-none transition-all focus:border-accent focus:ring-0 placeholder:text-foreground-muted/50"
                onChange={(event) => setChangeLog(event.target.value)}
                placeholder="Summarize what changed in this version."
                value={changeLog}
              />
            </label>
            <button
              className="mt-4 min-h-12 rounded-xl border border-border-default px-4 py-2 text-sm font-semibold text-foreground hover:bg-surface-3"
              onClick={handleCreateVersion}
              type="button"
            >
              Start draft version
            </button>
          </section>
        ) : null}
      </aside>
    </div>
  );
}

type ArtifactManifestProps = {
  artifacts: ArtifactResponse[];
  canRemove: boolean;
  onRemove: (artifactId: string) => void;
};

/** Processing state where the pipeline is actively running on the artifact. */
const IN_FLIGHT_PROCESSING = new Set(["processing"]);

/**
 * Render attached artifact status rows.
 *
 * @param props - Artifact list plus draft-only removal controls.
 */
function ArtifactManifest({
  artifacts,
  canRemove,
  onRemove,
}: ArtifactManifestProps) {
  return (
    <section className="rounded-2xl border border-border-default bg-surface-2 p-5 shadow-sm">
      <div className="flex items-center justify-between gap-3">
        <h2 className="font-heading text-lg font-bold text-foreground">
          Artifact manifest
        </h2>
        <span className="text-xs font-semibold uppercase tracking-[0.05em] text-foreground-muted">
          {artifacts.length} file{artifacts.length === 1 ? "" : "s"}
        </span>
      </div>
      {artifacts.length === 0 ? (
        <p className="mt-3 text-sm text-foreground-muted">
          No artifacts yet. Upload at least one file above.
        </p>
      ) : (
        <div className="mt-3 divide-y divide-border-default">
          {artifacts.map((artifact) => (
            <div
              className="flex items-start justify-between gap-3 py-3 text-sm"
              key={artifact.id}
            >
              <div className="min-w-0">
                <p className="truncate font-semibold text-foreground">
                  {artifact.name}
                </p>
                <p className="text-foreground-muted">
                  {formatFileSize(artifact.file_size)} · {artifact.scan_status} ·{" "}
                  {artifact.processing_status}
                </p>
              </div>
              {canRemove &&
              !IN_FLIGHT_PROCESSING.has(artifact.processing_status) ? (
                <button
                  aria-label={`Remove ${artifact.name}`}
                  className="shrink-0 rounded-lg border border-border-default px-3 py-1.5 text-xs font-semibold text-foreground-muted transition-colors hover:border-error/40 hover:bg-error/10 hover:text-error"
                  onClick={() => onRemove(artifact.id)}
                  type="button"
                >
                  Remove
                </button>
              ) : canRemove ? (
                <span className="shrink-0 text-xs font-medium text-foreground-muted">
                  Processing…
                </span>
              ) : null}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
