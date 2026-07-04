import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { GoogleDrivePicker } from "@/components/modules/artifacts/google-drive-picker";
import {
  importArtifactFromConnectorV1FrameworksFrameworkIdArtifactsFromConnectorPost,
  listConnectorFilesV1IntegrationsConnectorsProviderFilesGet,
  listConnectorsV1IntegrationsConnectorsGet,
} from "@/lib/generated/sdk.gen";
import type {
  ConnectorFileItem,
  ConnectorStatusItem,
} from "@/lib/generated/types.gen";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: () => "The request could not be completed.",
  getAccessTokenHeaders: () => ({ Authorization: "Bearer access-token" }),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  importArtifactFromConnectorV1FrameworksFrameworkIdArtifactsFromConnectorPost:
    vi.fn(),
  listConnectorFilesV1IntegrationsConnectorsProviderFilesGet: vi.fn(),
  listConnectorsV1IntegrationsConnectorsGet: vi.fn(),
}));

const listConnectors = vi.mocked(listConnectorsV1IntegrationsConnectorsGet);
const listFiles = vi.mocked(
  listConnectorFilesV1IntegrationsConnectorsProviderFilesGet,
);
const importArtifact = vi.mocked(
  importArtifactFromConnectorV1FrameworksFrameworkIdArtifactsFromConnectorPost,
);

const CONNECTED: ConnectorStatusItem = {
  provider: "google-drive",
  connected: true,
  connection_id: "11111111-1111-1111-1111-111111111111",
  status: "active",
  account_email: "pro@gmail.com",
};

const PDF_FILE: ConnectorFileItem = {
  id: "file-1",
  name: "playbook.pdf",
  mime_type: "application/pdf",
  size: 2048,
  modified_time: null,
  icon_link: null,
  importable: true,
};

const VIDEO_FILE: ConnectorFileItem = {
  id: "file-2",
  name: "clip.mp4",
  mime_type: "video/mp4",
  size: 4096,
  modified_time: null,
  icon_link: null,
  importable: false,
};

/** Mock the connectors lookup with the given items. */
function mockConnectors(connectors: ConnectorStatusItem[]): void {
  listConnectors.mockResolvedValue({
    data: { connectors },
    error: undefined,
    response: new Response(null, { status: 200 }),
  } as never);
}

/** Mock one files page. */
function mockFilesPage(
  files: ConnectorFileItem[],
  nextPageToken: string | null = null,
): void {
  listFiles.mockResolvedValue({
    data: { files, next_page_token: nextPageToken },
    error: undefined,
    response: new Response(null, { status: 200 }),
  } as never);
}

describe("GoogleDrivePicker", () => {
  beforeEach(() => {
    listConnectors.mockReset();
    listFiles.mockReset();
    importArtifact.mockReset();
  });

  it("prompts to open Connected Accounts when Drive is not connected", async () => {
    mockConnectors([{ ...CONNECTED, connected: false, connection_id: null }]);
    render(
      <GoogleDrivePicker frameworkId="fw-1" onArtifactCreated={vi.fn()} />,
    );
    expect(
      await screen.findByText("Connect Google Drive to import files directly."),
    ).toBeInTheDocument();
    expect(screen.getByRole("link")).toHaveAttribute(
      "href",
      "/settings/integrations",
    );
  });

  it("shows the reconnect prompt for a reauth_required connection", async () => {
    mockConnectors([{ ...CONNECTED, status: "reauth_required" }]);
    render(
      <GoogleDrivePicker frameworkId="fw-1" onArtifactCreated={vi.fn()} />,
    );
    expect(
      await screen.findByText(
        "Google Drive access expired. Reconnect to keep importing.",
      ),
    ).toBeInTheDocument();
  });

  it("lists files and disables non-importable ones", async () => {
    mockConnectors([CONNECTED]);
    mockFilesPage([PDF_FILE, VIDEO_FILE]);
    render(
      <GoogleDrivePicker frameworkId="fw-1" onArtifactCreated={vi.fn()} />,
    );
    expect(await screen.findByText("playbook.pdf")).toBeInTheDocument();
    expect(screen.getByText("clip.mp4")).toBeInTheDocument();

    const buttons = screen.getAllByRole("button", { name: "Import" });
    expect(buttons[0]).toBeEnabled();
    expect(buttons[1]).toBeDisabled();
  });

  it("imports a file with the stored connection id and reports the artifact", async () => {
    mockConnectors([CONNECTED]);
    mockFilesPage([PDF_FILE]);
    importArtifact.mockResolvedValue({
      data: { id: "artifact-1", processing_status: "processing" },
      error: undefined,
      response: new Response(null, { status: 200 }),
    } as never);
    const onArtifactCreated = vi.fn();

    render(
      <GoogleDrivePicker
        frameworkId="fw-1"
        onArtifactCreated={onArtifactCreated}
      />,
    );
    fireEvent.click(await screen.findByRole("button", { name: "Import" }));

    await waitFor(() => expect(onArtifactCreated).toHaveBeenCalledOnce());
    expect(importArtifact.mock.calls[0][0]).toMatchObject({
      path: { framework_id: "fw-1" },
      body: {
        connection_id: CONNECTED.connection_id,
        file_id: "file-1",
      },
    });
  });

  it("flips to the reconnect prompt when an import returns 409", async () => {
    mockConnectors([CONNECTED]);
    mockFilesPage([PDF_FILE]);
    importArtifact.mockResolvedValue({
      data: undefined,
      error: { detail: { error_code: "reauth_required" } },
      response: new Response(null, { status: 409 }),
    } as never);

    render(
      <GoogleDrivePicker frameworkId="fw-1" onArtifactCreated={vi.fn()} />,
    );
    fireEvent.click(await screen.findByRole("button", { name: "Import" }));
    expect(
      await screen.findByText(
        "Google Drive access expired. Reconnect to keep importing.",
      ),
    ).toBeInTheDocument();
  });

  it("surfaces backend errors such as 413/415 inline", async () => {
    mockConnectors([CONNECTED]);
    mockFilesPage([PDF_FILE]);
    importArtifact.mockResolvedValue({
      data: undefined,
      error: { detail: "Framework artifacts exceed the 500MB limit." },
      response: new Response(null, { status: 413 }),
    } as never);

    render(
      <GoogleDrivePicker frameworkId="fw-1" onArtifactCreated={vi.fn()} />,
    );
    fireEvent.click(await screen.findByRole("button", { name: "Import" }));
    expect(
      await screen.findByText("The request could not be completed."),
    ).toBeInTheDocument();
  });

  it("loads the next page when a cursor is present", async () => {
    mockConnectors([CONNECTED]);
    listFiles
      .mockResolvedValueOnce({
        data: { files: [PDF_FILE], next_page_token: "cursor-2" },
        error: undefined,
        response: new Response(null, { status: 200 }),
      } as never)
      .mockResolvedValueOnce({
        data: {
          files: [{ ...PDF_FILE, id: "file-9", name: "appendix.pdf" }],
          next_page_token: null,
        },
        error: undefined,
        response: new Response(null, { status: 200 }),
      } as never);

    render(
      <GoogleDrivePicker frameworkId="fw-1" onArtifactCreated={vi.fn()} />,
    );
    fireEvent.click(await screen.findByRole("button", { name: "Load more" }));
    expect(await screen.findByText("appendix.pdf")).toBeInTheDocument();
    expect(screen.getByText("playbook.pdf")).toBeInTheDocument();
  });
});
