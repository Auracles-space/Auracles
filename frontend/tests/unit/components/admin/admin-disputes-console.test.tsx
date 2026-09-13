import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AdminDisputesConsole } from "@/components/modules/admin/admin-disputes-console";

const nav = vi.hoisted(() => ({
  replace: vi.fn(),
  params: new URLSearchParams(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: nav.replace }),
  usePathname: () => "/admin/disputes",
  useSearchParams: () => nav.params,
}));

const sdk = vi.hoisted(() => ({
  attestation: vi.fn(),
  project: vi.fn(),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  listAdminAttestationDisputes: sdk.attestation,
  listAdminProjectDisputes: sdk.project,
}));

vi.mock("@/components/modules/admin/admin-attestation-disputes-panel", () => ({
  AdminAttestationDisputesPanel: () => <div>Attestation queue</div>,
}));
vi.mock("@/components/modules/admin/admin-disputes-panel", () => ({
  AdminDisputesPanel: () => <div>Project queue</div>,
}));

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer admin" })),
}));

const ok = <T,>(data: T) => ({ data, response: new Response(null, { status: 200 }) });

describe("AdminDisputesConsole", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    nav.params = new URLSearchParams();
    sdk.attestation.mockResolvedValue(ok({ disputes: [{ id: "d1" }, { id: "d2" }] }));
    sdk.project.mockResolvedValue(
      ok({ disputes: [{ id: "p1", status: "open" }, { id: "p2", status: "resolved" }] }),
    );
  });

  it("shows the attestation queue first with unresolved counts on both tabs", async () => {
    render(<AdminDisputesConsole />);

    expect(await screen.findByText("Attestation queue")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByRole("tab", { name: /Attestation/ })).toHaveTextContent("2"),
    );
    expect(screen.getByRole("tab", { name: /Project/ })).toHaveTextContent("1");
  });

  it("switches to the project queue and records the tab in the URL", async () => {
    render(<AdminDisputesConsole />);
    await screen.findByText("Attestation queue");

    fireEvent.click(screen.getByRole("tab", { name: /Project/ }));

    expect(await screen.findByText("Project queue")).toBeInTheDocument();
    expect(nav.replace).toHaveBeenCalledWith("/admin/disputes?tab=project", { scroll: false });
  });
});
