import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AdminAttestationPanel } from "@/components/modules/admin/admin-attestation-panel";
import {
  adminAssignAttestation,
  listAdminAttestations,
  listAttestorOrgs,
  listOrgAttestorApplicationsForAdmin,
} from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: vi.fn(() => "err"),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer admin" })),
}));
vi.mock("@/lib/generated/sdk.gen", () => ({
  listOrgAttestorApplicationsForAdmin: vi.fn(),
  listAdminAttestations: vi.fn(),
  listAttestorOrgs: vi.fn(),
  adminAssignAttestation: vi.fn(),
  adminRefundAttestation: vi.fn(),
  resolveAttestationDispute: vi.fn(),
}));

const ok = <T,>(data: T) => ({
  data, error: undefined,
  request: new Request("http://t"), response: new Response(null, { status: 200 }),
});

describe("AdminAttestationPanel", () => {
  beforeEach(() => vi.clearAllMocks());

  it("dispatches a needs-admin request to the selected attestor org", async () => {
    vi.mocked(listOrgAttestorApplicationsForAdmin).mockResolvedValue(
      ok({ applications: [] }) as never,
    );
    vi.mocked(listAttestorOrgs).mockResolvedValue(
      ok({ attestors: [{ org_id: "org-2", name: "Assurance Partners" }] }) as never,
    );
    vi.mocked(listAdminAttestations).mockResolvedValue(
      ok({
        attestations: [
          {
            id: "att-1",
            target_type: "framework",
            target_id: "fw-1",
            requestor_id: "user-1",
            attestor_org_id: null,
            status: "needs_admin",
            outcome: null,
            review_type: "quality",
            requested_specializations: [],
            requested_jurisdictions: [],
            fee_amount: "500.00",
            currency: "USD",
            escrow_id: "esc-1",
            created_at: "2026-07-16T00:00:00Z",
            updated_at: "2026-07-16T00:00:00Z",
          },
        ],
      }) as never,
    );
    vi.mocked(adminAssignAttestation).mockResolvedValue(ok({ id: "att-1" }) as never);
    render(<AdminAttestationPanel />);
    const row = (await screen.findByText("att-1")).closest("article");
    expect(row).not.toBeNull();
    const rowQueries = within(row as HTMLElement);

    fireEvent.change(rowQueries.getByLabelText(/Attestor org/i), {
      target: { value: "org-2" },
    });
    fireEvent.change(rowQueries.getByPlaceholderText("Reason for this action"), {
      target: { value: "Manual dispatch." },
    });
    fireEvent.click(rowQueries.getByRole("button", { name: /Assign to org/i }));

    await waitFor(() =>
      expect(vi.mocked(adminAssignAttestation)).toHaveBeenCalledWith(
        expect.objectContaining({
          path: { attestation_id: "att-1" },
          body: {
            attestor_org_id: "org-2",
            reason: "Manual dispatch.",
          },
        }),
      ),
    );
    expect(
      vi.mocked(adminAssignAttestation).mock.calls[0][0].body,
    ).not.toHaveProperty("reviewing_member_id");
  });

  it("labels a submitted report in the admin's vocabulary", async () => {
    vi.mocked(listOrgAttestorApplicationsForAdmin).mockResolvedValue(
      ok({ applications: [] }) as never,
    );
    vi.mocked(listAttestorOrgs).mockResolvedValue(ok({ attestors: [] }) as never);
    vi.mocked(listAdminAttestations).mockResolvedValue(
      ok({
        attestations: [
          {
            id: "att-2",
            target_type: "framework",
            target_id: "fw-1",
            requestor_id: "user-1",
            attestor_org_id: "org-2",
            status: "report_submitted",
            outcome: null,
            review_type: "quality",
            requested_specializations: [],
            requested_jurisdictions: [],
            fee_amount: "500.00",
            currency: "NGN",
            escrow_id: "esc-1",
            created_at: "2026-07-16T00:00:00Z",
            updated_at: "2026-07-16T00:00:00Z",
          },
        ],
      }) as never,
    );

    render(<AdminAttestationPanel />);

    // The read-only browse (any status but needs-admin) is what carries pills.
    fireEvent.change(await screen.findByLabelText("Status"), {
      target: { value: "report_submitted" },
    });

    expect(await screen.findByText("Submitted")).toBeInTheDocument();
    expect(screen.queryByText("Report ready")).toBeNull();
  });
});
