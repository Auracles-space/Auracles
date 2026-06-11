"use client";

/**
 * Contributor Framework edit workspace.
 *
 * Loads Framework metadata and artifacts, then composes the smaller action
 * components that call generated backend endpoints.
 */
import { useEffect, useState } from "react";

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
import { formatFileSize, formatLabel } from "@/lib/marketplace/format";

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
  const [error, setError] = useState<string | null>(null);
  const [framework, setFramework] = useState<FrameworkResponse | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function loadWorkspace() {
      configureBrowserClient();
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
        setError(describeGeneratedError(frameworkResult.error));
        setLoading(false);
        return;
      }

      setFramework(frameworkResult.data);
      setArtifacts(artifactsResult.data ?? []);
      setLoading(false);
    }

    void loadWorkspace();
  }, [frameworkId]);

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
        change_log: "Contributor draft version created from dashboard.",
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

  if (loading) {
    return <p className="text-sm text-foreground-muted">Loading workspace.</p>;
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
              {formatLabel(framework.status)}
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
        />
      </section>
      <aside className="grid gap-4">
        <ArtifactUploader
          frameworkId={framework.id}
          onUploaded={(artifact) =>
            setArtifacts((current) => [artifact, ...current])
          }
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
        <section className="rounded-2xl border border-border-default bg-surface-2 p-5 shadow-sm">
          <h2 className="font-heading text-lg font-bold text-foreground">
            Publish workflow
          </h2>
          <div className="mt-4 flex flex-wrap gap-3">
            <button
              className="min-h-11 rounded-[6px] border border-border-default px-4 py-2 text-sm font-semibold text-foreground hover:bg-surface-3"
              onClick={handleSubmitGate}
              type="button"
            >
              Submit to pipeline
            </button>
            <PublishButton disabled={!canPublish} frameworkId={framework.id} />
          </div>
          {framework.status === "published" ? (
            <div className="mt-4">
              <DelistButton frameworkId={framework.id} />
            </div>
          ) : null}
        </section>
        <section className="rounded-2xl border border-border-default bg-surface-2 p-5 shadow-sm">
          <h2 className="font-heading text-lg font-bold text-foreground">
            New version
          </h2>
          <div className="mt-4">
            <VersionRadios onChange={setChangeType} value={changeType} />
          </div>
          <button
            className="mt-4 min-h-11 rounded-[6px] border border-border-default px-4 py-2 text-sm font-semibold text-foreground hover:bg-surface-3"
            onClick={handleCreateVersion}
            type="button"
          >
            Start draft version
          </button>
        </section>
        <ArtifactManifest artifacts={artifacts} />
      </aside>
    </div>
  );
}

type ArtifactManifestProps = {
  artifacts: ArtifactResponse[];
};

/**
 * Render attached artifact status rows.
 *
 * @param props - Artifact list.
 */
function ArtifactManifest({ artifacts }: ArtifactManifestProps) {
  return (
    <section className="rounded-2xl border border-border-default bg-surface-2 p-5 shadow-sm">
      <h2 className="font-heading text-lg font-bold text-foreground">
        Artifact manifest
      </h2>
      <div className="mt-3 divide-y divide-border-default">
        {artifacts.map((artifact) => (
          <div className="py-3 text-sm" key={artifact.id}>
            <p className="font-semibold text-foreground">{artifact.name}</p>
            <p className="text-foreground-muted">
              {formatFileSize(artifact.file_size)} · {artifact.scan_status} ·{" "}
              {artifact.processing_status}
            </p>
          </div>
        ))}
      </div>
    </section>
  );
}
