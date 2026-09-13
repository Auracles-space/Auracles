import { render, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PendingInvitationsToast } from "@/components/modules/settings/pending-invitations-toast";
import { loadReceivedInvitations } from "@/lib/organizations/received-invitations";

const toastSuccess = vi.fn();
const storage = new Map<string, string>();

let mockPathname = "/dashboard";
vi.mock("next/navigation", () => ({ usePathname: () => mockPathname }));

vi.mock("@/components/ui/toast", () => ({
  useToast: () => ({ error: vi.fn(), success: toastSuccess }),
}));

vi.mock("@/lib/organizations/received-invitations", () => ({
  loadReceivedInvitations: vi.fn(),
}));

describe("PendingInvitationsToast", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    storage.clear();
    Object.defineProperty(window, "localStorage", {
      configurable: true,
      value: {
        getItem: vi.fn((key: string) => storage.get(key) ?? null),
        setItem: vi.fn((key: string, value: string) => {
          storage.set(key, value);
        }),
      },
    });
  });

  it("toasts once when there are pending invitations", async () => {
    vi.mocked(loadReceivedInvitations).mockResolvedValue(
      [{ id: "a" }, { id: "b" }] as never,
    );

    render(<PendingInvitationsToast />);

    await waitFor(() => expect(toastSuccess).toHaveBeenCalledTimes(1));

    render(<PendingInvitationsToast />);
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(toastSuccess).toHaveBeenCalledTimes(1);
  });

  it("stays quiet on the organizations page, where the inbox already shows them", async () => {
    mockPathname = "/dashboard/organizations";
    vi.mocked(loadReceivedInvitations).mockResolvedValue([
      { id: "inv-1" },
    ] as never);

    render(<PendingInvitationsToast />);

    // Nothing is even fetched: the inbox on that page owns the data.
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(loadReceivedInvitations).not.toHaveBeenCalled();
    expect(toastSuccess).not.toHaveBeenCalled();
    mockPathname = "/dashboard";
  });

  it("does not toast when there are none", async () => {
    vi.mocked(loadReceivedInvitations).mockResolvedValue([]);

    render(<PendingInvitationsToast />);
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(toastSuccess).not.toHaveBeenCalled();
  });
});
