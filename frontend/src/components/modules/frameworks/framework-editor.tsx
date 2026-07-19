"use client";

/**
 * Contributor Framework edit workspace.
 *
 * Loads Framework metadata and artifacts through a seller-scoped adapter, then
 * composes the smaller workflow controls.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { TableSkeleton } from "@/components/ui/skeletons/table-skeleton";

import { ArtifactManifest } from "@/components/modules/frameworks/artifact-manifest";
import { ArtifactUploader } from "@/components/modules/frameworks/artifact-uploader";
import { DelistButton } from "@/components/modules/frameworks/delist-button";
import { RelistButton } from "@/components/modules/frameworks/relist-button";
import { FrameworkForm } from "@/components/modules/frameworks/framework-form";
import { FrameworkPricingForm } from "@/components/modules/frameworks/framework-pricing-form";
import { PipelineStatusPanel } from "@/components/modules/frameworks/pipeline-status-panel";
import { PublishButton } from "@/components/modules/frameworks/publish-button";
import { SoftFailAcknowledgement } from "@/components/modules/frameworks/soft-fail-acknowledgement";
import { VersionRadios } from "@/components/modules/frameworks/version-radios";
import type {
  ArtifactResponse,
  FrameworkCreate,
  FrameworkResponse,
} from "@/lib/generated/types.gen";
import { useToast } from "@/components/ui/toast";
import {
  CONTRIBUTOR_GRANT_REQUIRED_MESSAGE,
  frameworkApiFor,
  isFrameworkApiErrorCode,
  type FrameworkSeller,
} from "@/lib/frameworks/framework-api";
import { formatFrameworkStatus } from "@/lib/marketplace/format";
import { deriveSubmitBlock } from "@/lib/frameworks/submit-block";

type FrameworkEditorProps = {
  basePath: string;
  canManageLiveState: boolean;
  frameworkId: string;
  seller: FrameworkSeller;
};

/**
 * Render the Contributor Framework edit screen.
 *
 * @param props - Framework id from the route.
 */
export function FrameworkEditor({
  basePath,
  canManageLiveState,
  frameworkId,
  seller,
}: FrameworkEditorProps) {
  const [artifacts, setArtifacts] = useState<ArtifactResponse[]>([]);
  const [changeType, setChangeType] = useState<"fix" | "improvement" | "major">(
    "improvement",
  );
  const [changeLog, setChangeLog] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [framework, setFramework] = useState<FrameworkResponse | null>(null);
  const [grantRequired, setGrantRequired] = useState(false);
  const [loading, setLoading] = useState(true);
  const toast = useToast();
  const api = useMemo(() => frameworkApiFor(seller), [seller]);

  // Reload framework + artifacts. `quiet` skips the loading skeleton so the
  // background poll never flashes the spinner over a populated workspace.
  const loadWorkspace = useCallback(
    async (quiet = false) => {
      if (!quiet) {
        setLoading(true);
      }
      try {
        const [loadedFramework, loadedArtifacts] = await Promise.all([
          api.get(frameworkId),
          api.listArtifacts(frameworkId),
        ]);
        setFramework(loadedFramework);
        setArtifacts(loadedArtifacts);
      } catch (caught) {
        if (!quiet) {
          if (
            isFrameworkApiErrorCode(caught, "capability_grant_required")
          ) {
            setGrantRequired(true);
            setLoading(false);
            return;
          }
          setError(
            caught instanceof Error
              ? caught.message
              : "The request could not be completed.",
          );
          setLoading(false);
        }
        return;
      }
      if (!quiet) {
        setLoading(false);
      }
    },
    [api, frameworkId],
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
    const updated = await api.update(frameworkId, payload);
    setFramework(updated);
  }

  async function handleSubmitGate() {
    // This action lives at the bottom of a long form; route the outcome to a
    // toast rather than a page-level error that would replace the whole editor
    // off-screen from the button.
    let updated: FrameworkResponse;
    try {
      updated = await api.submit(frameworkId);
      setFramework(updated);
    } catch (caught) {
      toast.error(
        caught instanceof Error
          ? caught.message
          : "The request could not be completed.",
      );
      return;
    }
    // The submit runs the gate synchronously, so an already-failed run comes
    // back here. Keep the toast short — the specific reason lives in the
    // inline summary by the button and the pipeline panel below.
    if (updated.status === "pipeline_failed") {
      toast.error("Publishing checks failed.");
      return;
    }
    toast.success("Publishing checks started.");
  }

  async function handleCreateVersion() {
    try {
      const updated = await api.startVersion(frameworkId, {
        artifact_inheritance: Object.fromEntries(
          artifacts.map((artifact) => [artifact.id, true]),
        ),
        change_log:
          changeLog.trim() ||
          "Contributor draft version created from dashboard.",
        change_type: changeType,
      });
      setFramework(updated);
    } catch (caught) {
      toast.error(
        caught instanceof Error
          ? caught.message
          : "The request could not be completed.",
      );
      return;
    }
    toast.success("Draft version started.");
  }

  async function handleRemoveArtifact(artifactId: string) {
    // Route through the seller adapter so org-owned Frameworks hit the
    // organization delete endpoint; the personal SDK path 404s on them.
    try {
      await api.deleteArtifact(frameworkId, artifactId);
    } catch (caught) {
      // A failed delete used to blank the whole editor; keep the workspace and
      // report the failure in a toast instead.
      toast.error(
        caught instanceof Error
          ? caught.message
          : "The request could not be completed.",
      );
      return;
    }
    setArtifacts((current) =>
      current.filter((artifact) => artifact.id !== artifactId),
    );
  }

  if (loading) {
    return <TableSkeleton />;
  }

  if (grantRequired) {
    return (
      <div className="rounded-2xl border border-border-default bg-surface-1 p-6 text-center shadow-sm sm:p-8">
        <h1 className="font-heading text-xl font-bold text-foreground">
          Contributor right required
        </h1>
        <p className="mx-auto mt-2 max-w-xl text-sm text-foreground-muted">
          {CONTRIBUTOR_GRANT_REQUIRED_MESSAGE}
        </p>
      </div>
    );
  }

  if (error || !framework) {
    return <p className="text-sm text-error">{error ?? "Framework not found."}</p>;
  }

  const hasRaritySoftFail = artifacts.some(
    (artifact) => artifact.processing_status === "flagged_rarity",
  );
  // Hard blocks (near-duplicate, virus, PII, processing failure) can only be
  // cleared by changing an artifact, so re-running checks is pointless until
  // then. Drive the disabled state and inline guidance from them.
  const submitBlock = deriveSubmitBlock(artifacts);
  const canRunChecks =
    framework.status === "draft" || framework.status === "pipeline_failed";
  // Accepting a redacted copy or re-running PII review flips the Framework to
  // `processing` and re-scans the file, which hides both action buttons. Surface
  // an explicit notice so the workspace never looks stuck mid-rescan.
  const isReprocessing =
    framework.status === "processing" || framework.status === "submitted";
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
        <Link
          className="mb-4 inline-flex min-h-11 items-center gap-1.5 text-sm font-semibold text-foreground-muted transition-colors hover:text-foreground"
          href={basePath}
        >
          <svg
            aria-hidden="true"
            className="h-4 w-4"
            fill="none"
            stroke="currentColor"
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth="2"
            viewBox="0 0 24 24"
          >
            <line x1="19" x2="5" y1="12" y2="12" />
            <polyline points="12 19 5 12 12 5" />
          </svg>
          Back to frameworks
        </Link>
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
          pricingInline={seller.kind === "user"}
          submitLabel="Save changes"
          readOnly={!isMetadataEditable}
          leftActions={
            canManageLiveState && isLive ? (
              <DelistButton
                api={api}
                frameworkId={framework.id}
                onCompleted={() => void loadWorkspace(true)}
              />
            ) : canManageLiveState && isDelisted ? (
              <RelistButton
                api={api}
                frameworkId={framework.id}
                onCompleted={() => void loadWorkspace(true)}
              />
            ) : null
          }
        >
          {canRunChecks && (
            <div className="flex flex-col gap-3">
              {submitBlock.reasons.length > 0 ? (
                <div className="rounded-xl border border-error/30 bg-error/10 p-4">
                  <p className="text-sm font-semibold text-error">
                    Resolve before running checks
                  </p>
                  <ul className="mt-2 grid gap-1.5">
                    {submitBlock.reasons.map((reason) => (
                      <li className="text-sm text-foreground-muted" key={reason.code}>
                        <span className="font-medium text-foreground">
                          {reason.label}.
                        </span>{" "}
                        {reason.hint}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
              <button
                className="inline-flex min-h-12 items-center justify-center rounded-xl bg-foreground px-6 py-2 text-sm font-semibold text-background shadow-sm outline-none transition-all hover:bg-foreground/90 focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-60 disabled:cursor-not-allowed"
                // Nothing to submit without an artifact, submitting mid-scan
                // would re-pick the in-flight job, and a hard block cannot pass
                // on retry until an artifact changes — gate on all three.
                disabled={
                  artifacts.length === 0 ||
                  isPipelineActive ||
                  submitBlock.hardBlocked
                }
                onClick={handleSubmitGate}
                type="button"
              >
                Run publishing checks
              </button>
            </div>
          )}
          {canManageLiveState && framework.status === "pipeline_passed" && (
            <PublishButton
              api={api}
              frameworkId={framework.id}
              onCompleted={() => void loadWorkspace(true)}
            />
          )}
          {/* A contributor member drives checks to a pass but cannot publish;
              live-state changes are reserved for org owners and admins. Explain
              the missing publish action rather than leaving a dead-end. */}
          {!canManageLiveState &&
            framework.status === "pipeline_passed" && (
              <div className="rounded-xl border border-success/30 bg-success/10 p-4">
                <p className="text-sm font-semibold text-success">
                  Ready to publish
                </p>
                <p className="mt-1 text-sm text-foreground-muted">
                  All checks passed. An organization owner or admin can publish
                  this framework to the marketplace.
                </p>
              </div>
            )}
          {isReprocessing && (
            <div className="rounded-xl border border-warning/30 bg-warning/10 p-4">
              <p className="text-sm font-semibold text-warning">
                Re-scanning your file…
              </p>
              <p className="mt-1 text-sm text-foreground-muted">
                Your update is going through the publishing checks again. The
                run-checks and publish actions reappear here once the scan
                finishes.
              </p>
            </div>
          )}
        </FrameworkForm>
      </section>
      <aside className="grid gap-4 min-w-0">
        {seller.kind === "org" && canManageLiveState && isMetadataEditable ? (
          // Pricing is metadata; the backend locks it outside draft/published/
          // delisted. Hide the editor while locked so a save cannot 422 — the
          // metadata-lock banner above already explains the state.
          <FrameworkPricingForm
            api={api}
            framework={framework}
            onUpdated={setFramework}
          />
        ) : null}
        <ArtifactUploader
          api={api}
          allowConnectorImport={seller.kind === "user"}
          artifactCount={artifacts.length}
          existingBytes={artifacts.reduce(
            (total, artifact) => total + artifact.file_size,
            0,
          )}
          frameworkId={framework.id}
          onUploaded={(artifact) =>
            // A background pipeline poll can replace the list with the server
            // copy that already includes this artifact before onUploaded fires;
            // dedupe by id so the manifest never renders duplicate React keys.
            setArtifacts((current) =>
              current.some((existing) => existing.id === artifact.id)
                ? current
                : [artifact, ...current],
            )
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
          setPreviewArtifact={(artifactId) =>
            api.setPreviewArtifact(framework.id, artifactId)
          }
        />
        <PipelineStatusPanel
          api={api}
          artifacts={artifacts}
          frameworkId={framework.id}
          frameworkStatus={framework.status}
          onResolved={() => void loadWorkspace(true)}
        />
        {hasRaritySoftFail ? (
          <SoftFailAcknowledgement
            api={api}
            frameworkId={framework.id}
            onAcknowledged={() => void loadWorkspace(true)}
          />
        ) : null}
        {/* Versioning applies once a Framework has been published at least once
            (live or delisted); a never-published draft is edited in place, so
            the new-version action stays hidden. */}
        {canManageLiveState && (isLive || isDelisted) ? (
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
