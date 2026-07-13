"use client";

/**
 * Contributor Framework edit workspace.
 *
 * Loads Framework metadata and artifacts, then composes the smaller action
 * components that call generated backend endpoints.
 */
import { useCallback, useEffect, useState } from "react";
import { TableSkeleton } from "@/components/ui/skeletons/table-skeleton";

import { ArtifactManifest } from "@/components/modules/frameworks/artifact-manifest";
import { ArtifactUploader } from "@/components/modules/frameworks/artifact-uploader";
import { DelistButton } from "@/components/modules/frameworks/delist-button";
import { RelistButton } from "@/components/modules/frameworks/relist-button";
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
import { useToast } from "@/components/ui/toast";
import { formatFrameworkStatus } from "@/lib/marketplace/format";

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
  const toast = useToast();

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
    // This action lives at the bottom of a long form; route the outcome to a
    // toast rather than a page-level error that would replace the whole editor
    // off-screen from the button.
    if (!result.response.ok || !result.data) {
      toast.error(describeGeneratedError(result.error));
      return;
    }
    setFramework(result.data);
    toast.success("Publishing checks started.");
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
      toast.error(describeGeneratedError(result.error));
      return;
    }
    setFramework(result.data);
    toast.success("Draft version started.");
  }

  async function handleRemoveArtifact(artifactId: string) {
    configureBrowserClient();
    const result = await deleteArtifact({
      headers: getAccessTokenHeaders(),
      path: { artifact_id: artifactId, framework_id: frameworkId },
    });
    // A failed delete used to blank the whole editor; keep the workspace and
    // report the failure in a toast instead.
    if (!result.response.ok) {
      toast.error(describeGeneratedError(result.error));
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
  const isLive = framework.status === "published";
  const isDelisted = framework.status === "unpublished";
  // Listing metadata (title, price, description, tags, taxonomy) is editable in
  // place while the Framework is a draft, live, or delisted; it stays locked
  // while moving through the pipeline or when suspended. Artifact changes still
  // require a new version. Mirrors the backend metadata-editable guard.
  const isMetadataEditable =
    framework.status === "draft" || isLive || isDelisted;

  return (
    <div className="grid gap-6 xl:grid-cols-[1fr_380px] min-w-0">
      <section className="min-w-0 rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm">
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
        {isLive || isDelisted ? (
          <p className="mb-4 rounded-xl border border-border-default bg-surface-2 px-4 py-3 text-sm text-foreground-muted">
            {isLive
              ? "This framework is live. Edits to title, price, and details save instantly without a new version. To change the files, start a new version."
              : "This framework is delisted. Edit its details below, relist it to restore the current version, or start a new version to change the files."}
          </p>
        ) : !isMetadataEditable ? (
          <p className="mb-4 rounded-xl border border-border-default bg-surface-2 px-4 py-3 text-sm text-foreground-muted">
            Details are locked while the framework moves through the publishing
            pipeline.
          </p>
        ) : null}
        <FrameworkForm
          framework={framework}
          onSubmit={handleUpdate}
          submitLabel="Save changes"
          readOnly={!isMetadataEditable}
          leftActions={
            isLive ? (
              <DelistButton
                frameworkId={framework.id}
                onCompleted={() => void loadWorkspace(true)}
              />
            ) : isDelisted ? (
              <RelistButton
                frameworkId={framework.id}
                onCompleted={() => void loadWorkspace(true)}
              />
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
              Run publishing checks
            </button>
          )}
          {framework.status === "pipeline_passed" && (
            <PublishButton
              frameworkId={framework.id}
              onCompleted={() => void loadWorkspace(true)}
            />
          )}
        </FrameworkForm>
      </section>
      <aside className="grid gap-4 min-w-0">
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
            framework.status === "pipeline_failed" ||
            framework.status === "pipeline_passed"
          }
          frameworkId={framework.id}
          frameworkStatus={framework.status}
          onPreviewSet={setFramework}
          onRemove={handleRemoveArtifact}
          previewArtifactId={framework.preview_artifact_id}
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
        {/* Versioning applies once a Framework has been published at least once
            (live or delisted); a never-published draft is edited in place, so
            the new-version action stays hidden. */}
        {isLive || isDelisted ? (
          <section className="min-w-0 rounded-2xl border border-border-default bg-surface-2 p-5 shadow-sm">
            <h2 className="font-heading text-lg font-bold text-foreground">
              New version
            </h2>
            <p className="mt-1 text-sm text-foreground-muted">
              {isLive
                ? "Start a draft revision. The current version stays published until the new one passes the pipeline."
                : "Start a draft revision to edit this delisted framework. It re-runs the pipeline before it can be published again."}
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
