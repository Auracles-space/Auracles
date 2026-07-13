import { render, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PendingInvitationsToast } from "@/components/modules/settings/pending-invitations-toast";
import { listReceivedInvitations } from "@/lib/generated/sdk.gen";

const toastSuccess = vi.fn();
const storage = new Map<string, string>();

vi.mock("@/components/ui/toast", () => ({
  useToast: () => ({ error: vi.fn(), success: toastSuccess }),
}));

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer t" })),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  listReceivedInvitations: vi.fn(),
}));

const ok = <T,>(data: T) => ({
  data,
  error: undefined,
  request: new Request("http://t"),
  response: new Response(null, { status: 200 }),
});

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
    vi.mocked(listReceivedInvitations).mockResolvedValue(
      ok({ invitations: [{ id: "a" }, { id: "b" }] }) as never,
    );

    render(<PendingInvitationsToast />);

    await waitFor(() => expect(toastSuccess).toHaveBeenCalledTimes(1));

    render(<PendingInvitationsToast />);
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(toastSuccess).toHaveBeenCalledTimes(1);
  });

  it("does not toast when there are none", async () => {
    vi.mocked(listReceivedInvitations).mockResolvedValue(
      ok({ invitations: [] }) as never,
    );

    render(<PendingInvitationsToast />);
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(toastSuccess).not.toHaveBeenCalled();
  });
});
