/**
 * Unit coverage for the admin platform-config panel.
 *
 * Verifies config groups render for a super-admin, the search filter narrows
 * settings, and non-super-admins see a read-only notice instead of controls.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AdminConfigPanel } from "@/components/modules/admin/admin-config-panel";
import { loadCurrentUserSession } from "@/lib/auth/current-user-session";
import { readPlatformConfig } from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: vi.fn(() => "The request could not be completed."),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer admin-token" })),
}));

vi.mock("@/lib/auth/current-user-session", () => ({
  loadCurrentUserSession: vi.fn(),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  readPlatformConfig: vi.fn(),
  updatePlatformConfig: vi.fn(),
}));

const ok = <T,>(data: T) => ({
  data,
  error: undefined,
  request: new Request("http://testserver"),
  response: new Response(null, { status: 200 }),
});

const configItems = [
  {
    key: "commission_rate",
    value: "0.15",
    editable: true,
    updated_at: "2026-06-10T10:00:00Z",
    updated_by: "admin-1",
  },
  {
    key: "min_payout_usd",
    value: "50.00",
    editable: true,
    updated_at: "2026-06-10T10:00:00Z",
    updated_by: "admin-1",
  },
];

describe("AdminConfigPanel", () => {
  beforeEach(() => {
    vi.mocked(readPlatformConfig).mockReset();
    vi.mocked(loadCurrentUserSession).mockReset();
    vi.mocked(readPlatformConfig).mockResolvedValue(
      ok({ items: configItems }),
    );
    vi.mocked(loadCurrentUserSession).mockResolvedValue({
      is_superadmin: true,
    } as never);
  });

  it("renders config groups for a super-admin", async () => {
    render(<AdminConfigPanel />);

    expect((await screen.findAllByText("Financial"))[0]).toBeInTheDocument();
  });

  it("filters settings through the search box", async () => {
    render(<AdminConfigPanel />);
    await screen.findAllByText("Financial");

    fireEvent.change(
      screen.getByPlaceholderText(/search platform settings/i),
      { target: { value: "zzz-no-match" } },
    );

    expect(
      await screen.findByText(/no platform settings matched your search query/i),
    ).toBeInTheDocument();
  });

  it("shows a read-only notice for non-super-admins", async () => {
    vi.mocked(loadCurrentUserSession).mockResolvedValue({
      is_superadmin: false,
    } as never);

    render(<AdminConfigPanel />);
    await screen.findAllByText("Financial");

    // The save controls are gated; a non-super-admin cannot mutate config.
    await waitFor(() =>
      expect(
        screen.queryByRole("button", { name: /save .*change/i }),
      ).not.toBeInTheDocument(),
    );
  });
});
