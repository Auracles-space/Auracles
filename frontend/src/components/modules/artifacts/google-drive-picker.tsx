"use client";

/**
 * Google Drive import picker for the contributor artifact uploader.
 *
 * Resolves the contributor's Drive connection, then offers a browsable
 * file list: folder navigation with a breadcrumb (My Drive root), a
 * global search, and pagination. Files import one-by-one or as a
 * checked multi-selection processed sequentially — each copies into the
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
  /** Called with each created artifact so the parent can start polling. */
  onArtifactCreated: (artifact: ArtifactResponse) => void;
};

type ConnectionState = "loading" | "ready" | "disconnected" | "reauth";

/** One breadcrumb segment of the folder path below My Drive. */
type FolderCrumb = { id: string; name: string };

/** A checked file pending batch import. */
type SelectedFile = { id: string; name: string };

/**
 * Browsable Drive picker that imports files as draft Artifacts.
 *
 * @param frameworkId - Framework receiving the imported artifacts.
 * @param onArtifactCreated - Callback fired per new processing artifact.
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
  const [folderPath, setFolderPath] = useState<FolderCrumb[]>([]);
  const [selected, setSelected] = useState<SelectedFile[]>([]);
  const [listLoading, setListLoading] = useState(false);
  const [importingId, setImportingId] = useState<string | null>(null);
  const [batchImporting, setBatchImporting] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadFiles = useCallback(
    async (query: string, pageToken: string | null, folderId: string | null) => {
      setListLoading(true);
      setError(null);
      configureBrowserClient();
      const result = await listConnectorFilesV1IntegrationsConnectorsProviderFilesGet({
        path: { provider: PROVIDER },
        query: {
          ...(query ? { query } : {}),
          ...(pageToken ? { page_token: pageToken } : {}),
          // Search is global across Drive; folder scope applies to browsing.
          ...(folderId && !query ? { folder_id: folderId } : {}),
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
      void loadFiles("", null, null);
    }
    void resolveConnection();
    return () => {
      mounted = false;
    };
  }, [loadFiles]);

  const currentFolderId =
    folderPath.length > 0 ? folderPath[folderPath.length - 1].id : null;

  /** Debounce search input into a fresh first-page load. */
  function handleSearchChange(value: string) {
    setSearch(value);
    if (debounceRef.current) {
      clearTimeout(debounceRef.current);
    }
    debounceRef.current = setTimeout(() => {
      void loadFiles(value, null, currentFolderId);
    }, SEARCH_DEBOUNCE_MS);
  }

  /** Enter a folder: push it onto the breadcrumb and list its children. */
  function openFolder(file: ConnectorFileItem) {
    const nextPath = [...folderPath, { id: file.id, name: file.name }];
    setFolderPath(nextPath);
    setSearch("");
    void loadFiles("", null, file.id);
  }

  /** Jump to a breadcrumb segment; index -1 is the My Drive root. */
  function jumpToCrumb(index: number) {
    const nextPath = index < 0 ? [] : folderPath.slice(0, index + 1);
    setFolderPath(nextPath);
    setSearch("");
    void loadFiles(
      "",
      null,
      nextPath.length > 0 ? nextPath[nextPath.length - 1].id : null,
    );
  }

  function toggleSelected(file: ConnectorFileItem) {
    setSelected((previous) =>
      previous.some((item) => item.id === file.id)
        ? previous.filter((item) => item.id !== file.id)
        : [...previous, { id: file.id, name: file.name }],
    );
  }

  /** Import one file; failures carry the human-readable backend reason. */
  async function importFile(
    fileId: string,
  ): Promise<{ outcome: "ok" | "reauth" | "failed"; message: string | null }> {
    setImportingId(fileId);
    configureBrowserClient();
    const result =
      await importArtifactFromConnectorV1FrameworksFrameworkIdArtifactsFromConnectorPost(
        {
          path: { framework_id: frameworkId },
          body: { connection_id: connectionId ?? "", file_id: fileId },
          headers: getAccessTokenHeaders(),
        },
      );
    setImportingId(null);
    if (result.response.ok && result.data) {
      onArtifactCreated(result.data);
      return { outcome: "ok", message: null };
    }
    if (result.response.status === 409) {
      return { outcome: "reauth", message: null };
    }
    return { outcome: "failed", message: describeGeneratedError(result.error) };
  }

  async function handleImport(file: ConnectorFileItem) {
    if (!connectionId) {
      return;
    }
    setError(null);
    const { outcome, message } = await importFile(file.id);
    if (outcome === "reauth") {
      setConnectionState("reauth");
    } else if (outcome === "failed") {
      setError(message);
    }
  }

  /** Import every checked file in order, keeping failures selected. */
  async function handleImportSelected() {
    if (!connectionId || selected.length === 0) {
      return;
    }
    setBatchImporting(true);
    setError(null);
    const failures: SelectedFile[] = [];
    for (const item of selected) {
      const { outcome } = await importFile(item.id);
      if (outcome === "reauth") {
        setBatchImporting(false);
        setConnectionState("reauth");
        return;
      }
      if (outcome === "failed") {
        failures.push(item);
      }
    }
    setBatchImporting(false);
    setSelected(failures);
    if (failures.length > 0) {
      setError(
        `Could not import: ${failures.map((item) => item.name).join(", ")}`,
      );
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

  const importBusy = batchImporting || importingId !== null;

  return (
    <div className="space-y-3">
      <Input
        onChange={(event) => handleSearchChange(event.target.value)}
        placeholder="Search all of your Drive"
        value={search}
      />
      {!search ? (
        <nav
          aria-label="Drive folders"
          className="flex flex-wrap items-center gap-1 text-xs text-foreground-muted"
        >
          <button
            className="min-h-11 rounded-lg px-2 font-semibold text-foreground transition-colors hover:bg-surface-2 disabled:text-foreground-muted"
            disabled={folderPath.length === 0}
            onClick={() => jumpToCrumb(-1)}
            type="button"
          >
            My Drive
          </button>
          {folderPath.map((crumb, index) => (
            <span className="flex items-center gap-1" key={crumb.id}>
              <span aria-hidden>/</span>
              <button
                className="min-h-11 rounded-lg px-2 font-semibold text-foreground transition-colors hover:bg-surface-2 disabled:text-foreground-muted"
                disabled={index === folderPath.length - 1}
                onClick={() => jumpToCrumb(index)}
                type="button"
              >
                {crumb.name}
              </button>
            </span>
          ))}
        </nav>
      ) : null}
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
            {search ? "No matching files in your Drive." : "This folder is empty."}
          </p>
        ) : null}
        {files.map((file) =>
          file.is_folder ? (
            <div
              className="flex items-center justify-between rounded-xl border border-border-default bg-surface-1 p-3"
              key={file.id}
            >
              <div className="mr-4 min-w-0 flex-1">
                <p className="truncate text-sm font-semibold text-foreground">
                  {file.name}
                </p>
                <p className="mt-0.5 text-xs text-foreground-muted">Folder</p>
              </div>
              <Button
                className="h-9 min-h-0 shrink-0 px-4 text-xs"
                disabled={importBusy}
                onClick={() => openFolder(file)}
                variant="secondary"
              >
                Open
              </Button>
            </div>
          ) : (
            <div
              className="flex items-center justify-between rounded-xl border border-border-default bg-surface-1 p-3"
              key={file.id}
            >
              <div className="mr-3 flex min-w-0 flex-1 items-center gap-2">
                {file.importable ? (
                  <label className="flex min-h-11 min-w-11 shrink-0 cursor-pointer items-center justify-center">
                    <input
                      aria-label={`Select ${file.name}`}
                      checked={selected.some((item) => item.id === file.id)}
                      className="h-5 w-5 accent-accent"
                      disabled={importBusy}
                      onChange={() => toggleSelected(file)}
                      type="checkbox"
                    />
                  </label>
                ) : null}
                <div className="min-w-0 flex-1">
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
              </div>
              <Button
                className="h-9 min-h-0 shrink-0 px-4 text-xs"
                disabled={!file.importable || importBusy}
                loading={importingId === file.id}
                onClick={() => void handleImport(file)}
                variant="secondary"
              >
                Import
              </Button>
            </div>
          ),
        )}
      </div>
      {selected.length > 0 ? (
        <Button
          className="w-full"
          disabled={importBusy}
          loading={batchImporting}
          onClick={() => void handleImportSelected()}
          variant="primary"
        >
          {`Import selected (${selected.length})`}
        </Button>
      ) : null}
      {nextPageToken ? (
        <Button
          className="w-full"
          disabled={listLoading}
          onClick={() => void loadFiles(search, nextPageToken, currentFolderId)}
          variant="secondary"
        >
          Load more
        </Button>
      ) : null}
    </div>
  );
}
