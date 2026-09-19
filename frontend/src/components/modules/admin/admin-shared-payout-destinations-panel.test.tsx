import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";

import {
  listSharedPayoutDestinations,
  setPayoutDestinationAllowance,
} from "@/lib/generated/sdk.gen";

import { AdminSharedPayoutDestinationsPanel } from "./admin-shared-payout-destinations-panel";

vi.mock("@/lib/generated/sdk.gen", () => ({
  listSharedPayoutDestinations: vi.fn(),
  setPayoutDestinationAllowance: vi.fn(),
}));

vi.mock("@/lib/auth/form-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/auth/form-client")>()),
  configureBrowserClient: vi.fn(),
  getAccessTokenHeaders: () => ({ Authorization: "Bearer test" }),
}));

/** One destination shared by a person and their company. */
function sharedDestination(): never {
  return {
    data: {
      destinations: [
        {
          provider: "paystack",
          lookup_hash: "a".repeat(64),
          provider_account_ref: "****4321",
          owner_count: 2,
          max_owners: 3,
          owners: [
            { kind: "user", id: "user-1", name: "Ada Lovelace" },
            { kind: "organization", id: "org-1", name: "Lovelace Ltd" },
          ],
        },
      ],
    },
    error: undefined,
    response: { ok: true },
  } as never;
}

describe("AdminSharedPayoutDestinationsPanel", () => {
  beforeEach(() => vi.clearAllMocks());

  it("names everyone collecting through one bank account", async () => {
    // The point of the queue: an admin can only judge whether a shared
    // account is a sole trader or a funnel by seeing who is behind it.
    vi.mocked(listSharedPayoutDestinations).mockResolvedValue(
      sharedDestination(),
    );

    render(<AdminSharedPayoutDestinationsPanel />);

    expect(await screen.findByText("****4321")).toBeInTheDocument();
    expect(screen.getByText("Ada Lovelace")).toBeInTheDocument();
    expect(screen.getByText("Lovelace Ltd")).toBeInTheDocument();
    expect(screen.getByText(/2 of 3/i)).toBeInTheDocument();
  });

  it("tells an admin when nothing is shared", async () => {
    // An empty queue is the expected state, not a failure to load.
    vi.mocked(listSharedPayoutDestinations).mockResolvedValue({
      data: { destinations: [] },
      error: undefined,
      response: { ok: true },
    } as never);

    render(<AdminSharedPayoutDestinationsPanel />);

    expect(
      await screen.findByText(/no bank account is shared/i),
    ).toBeInTheDocument();
  });

  it("raises the ceiling for one destination", async () => {
    vi.mocked(listSharedPayoutDestinations).mockResolvedValue(
      sharedDestination(),
    );
    vi.mocked(setPayoutDestinationAllowance).mockResolvedValue({
      data: {
        provider: "paystack",
        lookup_hash: "a".repeat(64),
        max_owners: 6,
        note: "Related entities.",
      },
      error: undefined,
      response: { ok: true },
    } as never);

    render(<AdminSharedPayoutDestinationsPanel />);
    fireEvent.click(await screen.findByRole("button", { name: /allow more/i }));
    fireEvent.change(screen.getByLabelText(/owners allowed/i), {
      target: { value: "6" },
    });
    fireEvent.change(screen.getByLabelText(/why/i), {
      target: { value: "Related entities." },
    });
    fireEvent.click(screen.getByRole("button", { name: /save allowance/i }));

    await waitFor(() =>
      expect(setPayoutDestinationAllowance).toHaveBeenCalledWith(
        expect.objectContaining({
          body: {
            provider: "paystack",
            lookup_hash: "a".repeat(64),
            max_owners: 6,
            note: "Related entities.",
          },
        }),
      ),
    );
  });
});
