"use client";

/**
 * Framework files panel (attestor workspace).
 *
 * Lists the framework artifacts the assigned reviewer is entitled to and hands
 * each one out as a short-lived presigned download. Access is server-gated: the
 * package endpoint returns the full artifact set only for the reviewing member
 * in an active review state, so an unentitled caller simply sees an empty list.
 *
 * Maps to: FR-ATT (attestor review workspace).
 */

import React, { useEffect, useState } from "react";
import { DownloadIcon, FileTextIcon } from "@radix-ui/react-icons";
import {
  getAttestationPackage,
  getAttestationArtifactAccess,
} from "@/lib/generated/sdk.gen";
import type { AttestationPackageArtifact } from "@/lib/generated/types.gen";
import { getAccessTokenHeaders, describeGeneratedError } from "@/lib/auth/form-client";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";

export interface FrameworkFilesPanelProps {
  attestationId: string;
}

/**
 * Renders the reviewer's downloadable framework artifacts for an attestation.
 *
 * @param attestationId - Attestation whose framework files are being reviewed.
 */
export function FrameworkFilesPanel({ attestationId }: FrameworkFilesPanelProps) {
  const [artifacts, setArtifacts] = useState<AttestationPackageArtifact[]>([]);
  const [entitlement, setEntitlement] = useState<string>("none");
  const [frameworkVersion, setFrameworkVersion] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [downloadingId, setDownloadingId] = useState<string | null>(null);

  useEffect(() => {
    async function loadPackage() {
      try {
        const res = await getAttestationPackage({
          path: { attestation_id: attestationId },
          headers: getAccessTokenHeaders(),
        });
        if (res.error) throw new Error(describeGeneratedError(res.error));
        setArtifacts(res.data.artifacts);
        setEntitlement(res.data.entitlement);
        setFrameworkVersion(res.data.framework_version ?? null);
      } catch (err: unknown) {
        setError(err instanceof Error ? err.message : "Failed to load files.");
      } finally {
        setLoading(false);
      }
    }
    loadPackage();
  }, [attestationId]);

  /** Fetch a fresh presigned URL and open the artifact in a new tab. */
  async function handleDownload(artifactId: string) {
    setDownloadingId(artifactId);
    setError(null);
    try {
      const res = await getAttestationArtifactAccess({
        path: { attestation_id: attestationId, artifact_id: artifactId },
        headers: getAccessTokenHeaders(),
      });
      if (res.error) throw new Error(describeGeneratedError(res.error));
      window.open(res.data.download_url, "_blank", "noopener,noreferrer");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to open file.");
    } finally {
      setDownloadingId(null);
    }
  }

  return (
    <div className="space-y-6">
      <div className="border-b border-border-default pb-4">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-xl font-semibold text-foreground">Framework files</h2>
          {frameworkVersion ? (
            <span className="inline-flex items-center rounded-full border border-border-default bg-surface-elevated px-2.5 py-0.5 text-xs font-semibold text-foreground-muted">
              Version {frameworkVersion}
            </span>
          ) : null}
        </div>
        <p className="mt-1 text-sm text-foreground-muted">
          The artifacts submitted for review. Downloads are time-limited to you.
        </p>
      </div>

      {loading ? (
        <div className="flex justify-center p-8">
          <Spinner className="h-6 w-6 text-accent" />
        </div>
      ) : error ? (
        <div className="p-4 text-sm text-error bg-error/5 rounded-xl border border-error/50">
          {error}
        </div>
      ) : entitlement !== "full" || artifacts.length === 0 ? (
        <div className="p-4 text-sm text-foreground-muted bg-surface-elevated rounded-xl border border-border-default">
          No framework files are available for this review yet.
        </div>
      ) : (
        <ul className="space-y-3">
          {artifacts.map((artifact) => (
            <li
              key={artifact.id}
              className="flex items-center justify-between gap-4 rounded-xl border border-border-default bg-surface-elevated p-4"
            >
              <div className="flex min-w-0 items-center gap-3">
                <FileTextIcon className="h-5 w-5 flex-shrink-0 text-foreground-muted" />
                <span className="truncate text-sm font-medium text-foreground">
                  {artifact.filename ?? "Untitled file"}
                </span>
              </div>
              <Button
                variant="secondary"
                onClick={() => handleDownload(artifact.id)}
                loading={downloadingId === artifact.id}
                disabled={downloadingId !== null}
                className="flex-shrink-0"
              >
                <DownloadIcon className="mr-1.5 h-4 w-4" /> Download
              </Button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
