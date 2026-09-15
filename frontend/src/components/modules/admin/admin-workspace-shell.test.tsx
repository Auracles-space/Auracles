import { act, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { adminListOrgsV1AdminOrgsGet, listAdminAttestations } from "@/lib/generated/sdk.gen";
import { AdminWorkspaceShell } from "./admin-workspace-shell";
import { NEEDS_ADMIN_CHANGED_EVENT, ORG_VERIFICATION_CHANGED_EVENT } from "./admin-events";

vi.mock("next/navigation", () => ({
  usePathname: () => "/admin/attestations",
}));

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer test" })),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  adminListOrgsV1AdminOrgsGet: vi.fn(),
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

describe("AdminWorkspaceShell organization verification badge", () => {
  it("shows how many organizations await verification beside Organizations", async () => {
    vi.mocked(listAdminAttestations).mockResolvedValue({
      response: { ok: true },
      data: { attestations: [] },
    } as never);
    vi.mocked(adminListOrgsV1AdminOrgsGet).mockResolvedValue({
      response: { ok: true },
      data: { orgs: [{ id: "org-1" }], page: 1, page_size: 1, total: 3 },
    } as never);

    render(
      <AdminWorkspaceShell>
        <div>content</div>
      </AdminWorkspaceShell>,
    );

    // The total, not the page length: the request asks for one row.
    expect(await screen.findByLabelText("3 needing attention")).toHaveTextContent("3");
    expect(adminListOrgsV1AdminOrgsGet).toHaveBeenCalledWith(
      expect.objectContaining({ query: expect.objectContaining({ kyb_status: "pending" }) }),
    );
  });

  it("refetches the count when a verification decision is recorded", async () => {
    vi.mocked(listAdminAttestations).mockResolvedValue({
      response: { ok: true },
      data: { attestations: [] },
    } as never);
    vi.mocked(adminListOrgsV1AdminOrgsGet)
      .mockResolvedValueOnce({
        response: { ok: true },
        data: { orgs: [], page: 1, page_size: 1, total: 1 },
      } as never)
      .mockResolvedValueOnce({
        response: { ok: true },
        data: { orgs: [], page: 1, page_size: 1, total: 0 },
      } as never);

    render(
      <AdminWorkspaceShell>
        <div>content</div>
      </AdminWorkspaceShell>,
    );
    await screen.findByLabelText("1 needing attention");

    act(() => {
      window.dispatchEvent(new Event(ORG_VERIFICATION_CHANGED_EVENT));
    });

    await waitFor(() => expect(screen.queryByLabelText(/needing attention/)).toBeNull());
  });
});

describe("AdminWorkspaceShell badge freshness", () => {
  it("refetches the counts when the admin returns to the tab", async () => {
    // Badges loaded once on mount, so an application submitted while the admin
    // page was open never showed a count.
    vi.mocked(listAdminAttestations).mockReset();
    vi.mocked(adminListOrgsV1AdminOrgsGet).mockReset();
    vi.mocked(listAdminAttestations)
      .mockResolvedValueOnce({ response: { ok: true }, data: { attestations: [] } } as never)
      .mockResolvedValue({
        response: { ok: true },
        data: { attestations: [{ id: "att-1" }] },
      } as never);
    vi.mocked(adminListOrgsV1AdminOrgsGet).mockResolvedValue({
      response: { ok: true },
      data: { orgs: [], page: 1, page_size: 1, total: 0 },
    } as never);

    render(
      <AdminWorkspaceShell>
        <div>content</div>
      </AdminWorkspaceShell>,
    );
    await waitFor(() => expect(listAdminAttestations).toHaveBeenCalledTimes(1));
    expect(screen.queryByLabelText(/needing attention/)).toBeNull();

    act(() => {
      window.dispatchEvent(new Event("focus"));
    });

    expect(await screen.findByLabelText("1 needing attention")).toBeInTheDocument();
  });
});
