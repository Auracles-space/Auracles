"use client";

/**
 * Google Drive import picker for the contributor artifact uploader.
 *
 * Resolves the contributor's Drive connection, then offers a searched,
 * paginated file list. Selecting an importable file copies it into the
 * framework as a normal processing artifact via the from-connector
 * endpoint. Handles the no-connection and reauth-required states with a
 * pointer to Connected Accounts settings.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import {
  importArtifactFromConnectorV1FrameworksFrameworkIdArtifactsFromConnectorPost,
  listConnectorFilesV1IntegrationsConnectorsProviderFilesGet,
  listConnectorsV1IntegrationsConnectorsGet,
} from "@/lib/generated/sdk.gen";
import type {
  ArtifactResponse,
  ConnectorFileItem,
  ConnectorStatusItem,
} from "@/lib/generated/types.gen";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";

const PROVIDER = "google-drive";
const SEARCH_DEBOUNCE_MS = 350;

type GoogleDrivePickerProps = {
  /** Framework receiving the imported artifact. */
  frameworkId: string;
  /** Called with the created artifact so the parent can start polling. */
  onArtifactCreated: (artifact: ArtifactResponse) => void;
};

type ConnectionState = "loading" | "ready" | "disconnected" | "reauth";

/**
 * Search-driven Drive file picker that imports a file as a draft Artifact.
 *
 * @param frameworkId - Framework receiving the imported artifact.
 * @param onArtifactCreated - Callback fired with the new processing artifact.
 */
export function GoogleDrivePicker({
  frameworkId,
  onArtifactCreated,
}: GoogleDrivePickerProps) {
  const [connectionState, setConnectionState] = useState<ConnectionState>("loading");
  const [connectionId, setConnectionId] = useState<string | null>(null);
  const [files, setFiles] = useState<ConnectorFileItem[]>([]);
  const [nextPageToken, setNextPageToken] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [listLoading, setListLoading] = useState(false);
  const [importingId, setImportingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const loadFiles = useCallback(
    async (query: string, pageToken: string | null) => {
      setListLoading(true);
      setError(null);
      configureBrowserClient();
      const result = await listConnectorFilesV1IntegrationsConnectorsProviderFilesGet({
        path: { provider: PROVIDER },
        query: {
          ...(query ? { query } : {}),
          ...(pageToken ? { page_token: pageToken } : {}),
        },
        headers: getAccessTokenHeaders(),
      });
      if (result.response.ok && result.data) {
        setFiles((previous) =>
          pageToken ? [...previous, ...result.data.files] : result.data.files,
        );
        setNextPageToken(result.data.next_page_token ?? null);
      } else if (result.response.status === 409) {
        setConnectionState("reauth");
      } else {
        setError(describeGeneratedError(result.error));
      }
      setListLoading(false);
    },
    [],
  );

  useEffect(() => {
    let mounted = true;
    async function resolveConnection() {
      configureBrowserClient();
      const result = await listConnectorsV1IntegrationsConnectorsGet({
        headers: getAccessTokenHeaders(),
      });
      if (!mounted) {
        return;
      }
      if (!result.response.ok || !result.data) {
        setConnectionState("disconnected");
        setError(describeGeneratedError(result.error));
        return;
      }
      const drive = result.data.connectors.find(
        (connector: ConnectorStatusItem) => connector.provider === PROVIDER,
      );
      if (!drive?.connected || !drive.connection_id) {
        setConnectionState("disconnected");
        return;
      }
      if (drive.status === "reauth_required") {
        setConnectionState("reauth");
        return;
      }
      setConnectionId(drive.connection_id);
      setConnectionState("ready");
      void loadFiles("", null);
    }
    void resolveConnection();
    return () => {
      mounted = false;
    };
  }, [loadFiles]);

  /** Debounce search input into a fresh first-page load. */
  function handleSearchChange(value: string) {
    setSearch(value);
    if (debounceRef.current) {
      clearTimeout(debounceRef.current);
    }
    debounceRef.current = setTimeout(() => {
      void loadFiles(value, null);
    }, SEARCH_DEBOUNCE_MS);
  }

  async function handleImport(file: ConnectorFileItem) {
    if (!connectionId) {
      return;
    }
    setImportingId(file.id);
    setError(null);
    configureBrowserClient();
    const result =
      await importArtifactFromConnectorV1FrameworksFrameworkIdArtifactsFromConnectorPost(
        {
          path: { framework_id: frameworkId },
          body: { connection_id: connectionId, file_id: file.id },
          headers: getAccessTokenHeaders(),
        },
      );
    setImportingId(null);
    if (result.response.ok && result.data) {
      onArtifactCreated(result.data);
    } else if (result.response.status === 409) {
      setConnectionState("reauth");
    } else {
      setError(describeGeneratedError(result.error));
    }
  }

  if (connectionState === "loading") {
    return (
      <div className="flex items-center justify-center p-8">
        <Spinner className="h-6 w-6" />
      </div>
    );
  }

  if (connectionState === "disconnected" || connectionState === "reauth") {
    return (
      <div className="rounded-xl border border-border-default bg-surface-1 p-6 text-center">
        <p className="text-sm text-foreground-muted">
          {connectionState === "reauth"
            ? "Google Drive access expired. Reconnect to keep importing."
            : "Connect Google Drive to import files directly."}
        </p>
        <Link
          className="mt-3 inline-flex min-h-11 items-center justify-center rounded-xl border border-border-default bg-surface-2 px-5 text-sm font-semibold text-foreground transition-colors hover:bg-surface-1"
          href="/settings/integrations"
        >
          {connectionState === "reauth" ? "Reconnect in settings" : "Open Connected Accounts"}
        </Link>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <Input
        onChange={(event) => handleSearchChange(event.target.value)}
        placeholder="Search your Drive files"
        value={search}
      />
      {error ? (
        <p className="rounded-xl border border-error/30 bg-error/10 p-3 text-sm text-error">
          {error}
        </p>
      ) : null}
      <div className="scrollbar-none grid max-h-96 gap-2 overflow-y-auto pr-2">
        {listLoading && files.length === 0 ? (
          <div className="flex items-center justify-center p-8">
            <Spinner className="h-6 w-6" />
          </div>
        ) : null}
        {!listLoading && files.length === 0 ? (
          <p className="p-6 text-center text-sm text-foreground-muted">
            No matching files in your Drive.
          </p>
        ) : null}
        {files.map((file) => (
          <div
            className="flex items-center justify-between rounded-xl border border-border-default bg-surface-1 p-3"
            key={file.id}
          >
            <div className="mr-4 min-w-0 flex-1">
              <p className="truncate text-sm font-semibold text-foreground">
                {file.name}
              </p>
              <p className="mt-0.5 text-xs text-foreground-muted">
                {file.size != null
                  ? `${(file.size / 1024).toFixed(1)} KB`
                  : "Google document"}
                {!file.importable ? " · Not importable" : ""}
              </p>
            </div>
            <Button
              className="h-9 min-h-0 shrink-0 px-4 text-xs"
              disabled={
                !file.importable ||
                (importingId !== null && importingId !== file.id)
              }
              loading={importingId === file.id}
              onClick={() => void handleImport(file)}
              variant="secondary"
            >
              Import
            </Button>
          </div>
        ))}
      </div>
      {nextPageToken ? (
        <Button
          className="w-full"
          disabled={listLoading}
          onClick={() => void loadFiles(search, nextPageToken)}
          variant="secondary"
        >
          Load more
        </Button>
      ) : null}
    </div>
  );
}
