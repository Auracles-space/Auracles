import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { IntegrationsList } from "@/components/modules/settings/integrations-list";
import {
  connectProviderV1IntegrationsConnectorsProviderConnectPost,
  disconnectProviderV1IntegrationsConnectorsProviderDelete,
  listConnectorsV1IntegrationsConnectorsGet,
} from "@/lib/generated/sdk.gen";
import type { ConnectorStatusItem } from "@/lib/generated/types.gen";

const searchParams = { value: new URLSearchParams() };

vi.mock("next/navigation", () => ({
  useSearchParams: () => searchParams.value,
}));

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: () => "The request could not be completed.",
  getAccessTokenHeaders: () => ({ Authorization: "Bearer access-token" }),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  connectProviderV1IntegrationsConnectorsProviderConnectPost: vi.fn(),
  disconnectProviderV1IntegrationsConnectorsProviderDelete: vi.fn(),
  listConnectorsV1IntegrationsConnectorsGet: vi.fn(),
}));

const listConnectors = vi.mocked(listConnectorsV1IntegrationsConnectorsGet);
const connectProvider = vi.mocked(
  connectProviderV1IntegrationsConnectorsProviderConnectPost,
);
const disconnectProvider = vi.mocked(
  disconnectProviderV1IntegrationsConnectorsProviderDelete,
);

/** Mock the connectors list response with the given items. */
function mockConnectors(connectors: ConnectorStatusItem[]): void {
  listConnectors.mockResolvedValue({
    data: { connectors },
    error: undefined,
    response: new Response(null, { status: 200 }),
  } as never);
}

const DISCONNECTED: ConnectorStatusItem = {
  provider: "google-drive",
  connected: false,
  connection_id: null,
  status: null,
  account_email: null,
};

const CONNECTED: ConnectorStatusItem = {
  provider: "google-drive",
  connected: true,
  connection_id: "11111111-1111-1111-1111-111111111111",
  status: "active",
  account_email: "pro@gmail.com",
};

describe("IntegrationsList", () => {
  beforeEach(() => {
    listConnectors.mockReset();
    connectProvider.mockReset();
    disconnectProvider.mockReset();
    searchParams.value = new URLSearchParams();
  });

  it("offers Connect when Google Drive is not connected", async () => {
    mockConnectors([DISCONNECTED]);
    render(<IntegrationsList />);
    expect(await screen.findByText("Connect")).toBeInTheDocument();
    expect(screen.queryByText("Disconnect")).not.toBeInTheDocument();
  });

  it("shows the connected account and a confirmed disconnect flow", async () => {
    mockConnectors([CONNECTED]);
    disconnectProvider.mockResolvedValue({
      data: undefined,
      error: undefined,
      response: new Response(null, { status: 204 }),
    } as never);

    render(<IntegrationsList />);
    expect(await screen.findByText("Connected as pro@gmail.com")).toBeInTheDocument();

    fireEvent.click(screen.getByText("Disconnect"));
    expect(disconnectProvider).not.toHaveBeenCalled();

    fireEvent.click(screen.getByText("Confirm disconnect"));
    await waitFor(() => expect(disconnectProvider).toHaveBeenCalledOnce());
    expect(disconnectProvider.mock.calls[0][0]).toMatchObject({
      path: { provider: "google-drive" },
    });
  });

  it("treats reauth_required as a Reconnect state, not a silent failure", async () => {
    mockConnectors([{ ...CONNECTED, status: "reauth_required" }]);
    render(<IntegrationsList />);
    expect(await screen.findByText("Reconnect")).toBeInTheDocument();
    expect(
      screen.getByText("Access expired — reconnect to keep importing."),
    ).toBeInTheDocument();
  });

  it("starts the consent flow and navigates to the authorization URL", async () => {
    mockConnectors([DISCONNECTED]);
    connectProvider.mockResolvedValue({
      data: { authorization_url: "https://accounts.google.com/consent" },
      error: undefined,
      response: new Response(null, { status: 200 }),
    } as never);
    const assign = vi.fn();
    vi.stubGlobal("location", { ...window.location, assign });

    render(<IntegrationsList />);
    fireEvent.click(await screen.findByText("Connect"));
    await waitFor(() =>
      expect(assign).toHaveBeenCalledWith("https://accounts.google.com/consent"),
    );
    vi.unstubAllGlobals();
  });

  it("renders the callback outcome banner from query params", async () => {
    searchParams.value = new URLSearchParams(
      "connector=google-drive&status=connected",
    );
    mockConnectors([CONNECTED]);
    render(<IntegrationsList />);
    expect(await screen.findByText("Google Drive connected.")).toBeInTheDocument();
  });

  it("renders the denied banner when consent was cancelled", async () => {
    searchParams.value = new URLSearchParams(
      "connector=google-drive&status=denied",
    );
    mockConnectors([DISCONNECTED]);
    render(<IntegrationsList />);
    expect(
      await screen.findByText("Connection cancelled — access was not granted."),
    ).toBeInTheDocument();
  });
});
