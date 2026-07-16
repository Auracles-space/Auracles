import { act, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { listAdminAttestations } from "@/lib/generated/sdk.gen";
import { AdminWorkspaceShell } from "./admin-workspace-shell";
import { NEEDS_ADMIN_CHANGED_EVENT } from "./admin-events";

vi.mock("next/navigation", () => ({
  usePathname: () => "/admin/attestations",
}));

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer test" })),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  listAdminAttestations: vi.fn(),
}));

describe("AdminWorkspaceShell needs-admin badge", () => {
  it("shows the needs-admin count beside the Attestations link", async () => {
    vi.mocked(listAdminAttestations).mockResolvedValue({
      response: { ok: true },
      data: { attestations: [{ id: "att-1" }, { id: "att-2" }] },
    } as never);

    render(
      <AdminWorkspaceShell>
        <div>content</div>
      </AdminWorkspaceShell>,
    );

    expect(
      await screen.findByLabelText("2 needing attention"),
    ).toHaveTextContent("2");
  });

  it("shows no badge when the queue is empty", async () => {
    vi.mocked(listAdminAttestations).mockResolvedValue({
      response: { ok: true },
      data: { attestations: [] },
    } as never);

    render(
      <AdminWorkspaceShell>
        <div>content</div>
      </AdminWorkspaceShell>,
    );

    await waitFor(() => expect(listAdminAttestations).toHaveBeenCalled());
    expect(screen.queryByLabelText(/needing attention/)).toBeNull();
  });

  it("refetches the count when a needs-admin change event fires", async () => {
    vi.mocked(listAdminAttestations)
      .mockResolvedValueOnce({
        response: { ok: true },
        data: { attestations: [{ id: "att-1" }] },
      } as never)
      .mockResolvedValueOnce({
        response: { ok: true },
        data: { attestations: [] },
      } as never);

    render(
      <AdminWorkspaceShell>
        <div>content</div>
      </AdminWorkspaceShell>,
    );
    await screen.findByLabelText("1 needing attention");

    act(() => {
      window.dispatchEvent(new Event(NEEDS_ADMIN_CHANGED_EVENT));
    });

    await waitFor(() =>
      expect(screen.queryByLabelText(/needing attention/)).toBeNull(),
    );
  });
});
