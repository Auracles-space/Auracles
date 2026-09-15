/**
 * Unit coverage for the admin business-verification (KYB) queue.
 *
 * Verifies each pending organization carries the shared "In review" status
 * pill, that load and verdict failures surface the API's described error,
 * and that every decision control meets the 44px touch-target minimum.
 */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AdminOrgVerificationQueue } from "@/components/modules/admin/admin-org-verification-queue";
import {
  adminListOrgsV1AdminOrgsGet,
  adminOrgVerificationV1AdminOrgsOrgIdVerificationGet,
  adminReviewOrgKyb,
} from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: vi.fn(
    (error: { detail?: string } | undefined) =>
      error?.detail ?? "The request could not be completed.",
  ),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer admin-token" })),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  adminListOrgsV1AdminOrgsGet: vi.fn(),
  adminOrgVerificationV1AdminOrgsOrgIdVerificationGet: vi.fn(),
  adminReviewOrgKyb: vi.fn(),
}));

const ok = <T,>(data: T) => ({
  data,
  error: undefined,
  request: new Request("http://t"),
  response: new Response(null, { status: 200 }),
});

const failed = (status: number, detail: string) => ({
  data: undefined,
  error: { detail },
  request: new Request("http://t"),
  response: new Response(null, { status }),
});

const pendingOrg = {
  id: "org-pending",
  name: "Lagos Advisory",
  legal_name: "Lagos Advisory Limited",
  registration_number: "RC-123456",
  slug: "lagos-advisory",
  country: "NG",
  member_count: 2,
  capabilities: {},
  created_at: "2026-09-01T00:00:00Z",
  kyb_status: "pending",
};

describe("AdminOrgVerificationQueue", () => {
  beforeEach(() => {
    vi.mocked(adminListOrgsV1AdminOrgsGet).mockReset();
    vi.mocked(adminReviewOrgKyb).mockReset();
    vi.mocked(adminListOrgsV1AdminOrgsGet).mockResolvedValue(
      ok({ orgs: [pendingOrg], page: 1, page_size: 50, total: 1 }) as never,
    );
  });

  it("loads an organization's documents on request and links each one", async () => {
    // Minting the links is audited and they expire in 5 minutes, so the queue
    // fetches them only when the admin asks, not on page load.
    vi.mocked(adminOrgVerificationV1AdminOrgsOrgIdVerificationGet).mockResolvedValue(
      ok({
        documents: [
          {
            download_url: "https://s3.test/cert.pdf?sig=1",
            file_name: "cac-certificate.pdf",
            kind: "incorporation_document",
          },
        ],
      }) as never,
    );
    render(<AdminOrgVerificationQueue />);

    const article = (await screen.findByText("Lagos Advisory Limited")).closest(
      "article",
    ) as HTMLElement;
    expect(adminOrgVerificationV1AdminOrgsOrgIdVerificationGet).not.toHaveBeenCalled();

    fireEvent.click(within(article).getByRole("button", { name: "Show documents" }));

    const link = await within(article).findByRole("link", { name: "Open cac-certificate.pdf" });
    expect(link).toHaveAttribute("href", "https://s3.test/cert.pdf?sig=1");
    expect(link).toHaveAttribute("target", "_blank");
    expect(adminOrgVerificationV1AdminOrgsOrgIdVerificationGet).toHaveBeenCalledWith(
      expect.objectContaining({ path: { org_id: "org-pending" } }),
    );
  });

  it("marks each pending organization with the shared In review pill", async () => {
    render(<AdminOrgVerificationQueue />);

    const article = (await screen.findByText("Lagos Advisory Limited")).closest(
      "article",
    ) as HTMLElement;
    const pill = within(article).getByText("In review");
    expect(pill.className).toContain("rounded-badge");
    expect(within(article).queryByText("Awaiting review")).not.toBeInTheDocument();
  });

  it("shows the described error when the queue fails to load", async () => {
    vi.mocked(adminListOrgsV1AdminOrgsGet).mockResolvedValue(
      failed(403, "Admin role required.") as never,
    );
    render(<AdminOrgVerificationQueue />);

    expect(await screen.findByText("Admin role required.")).toBeInTheDocument();
  });

  it("shows the described error when a verdict is refused", async () => {
    vi.mocked(adminReviewOrgKyb).mockResolvedValue(
      failed(409, "This organization was already decided.") as never,
    );
    render(<AdminOrgVerificationQueue />);

    fireEvent.click(await screen.findByRole("button", { name: "Verify organization" }));

    expect(
      await screen.findByText("This organization was already decided."),
    ).toBeInTheDocument();
  });

  it("gives every decision control at least a 44px touch target", async () => {
    render(<AdminOrgVerificationQueue />);

    await screen.findByText("Lagos Advisory Limited");
    for (const name of ["Verify organization", "Return for changes"]) {
      expect(screen.getByRole("button", { name }).className).toMatch(/min-h-(11|12)/);
    }
  });
});
