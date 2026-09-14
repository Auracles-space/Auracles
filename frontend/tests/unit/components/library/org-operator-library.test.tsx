/**
 * Organization shared-library access tests.
 *
 * Verifies that granted members can consume Frameworks without receiving
 * organization-admin review or license-allocation controls.
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { OrgOperatorLibrary } from "@/components/modules/library/org-operator-library";
import { OrganizationProvider } from "@/components/modules/organizations/organization-context";
import {
  getExploreFrameworkDetail,
  listOrgLibrary,
} from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: (error: { detail?: string } | undefined) =>
    error?.detail ?? "The request could not be completed.",
  getAccessTokenHeaders: () => ({ Authorization: "Bearer access-token" }),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  client: { setConfig: vi.fn() },
  getExploreFrameworkDetail: vi.fn(),
  listOrgLibrary: vi.fn(),
  requestOrgLibraryArtifactDownload: vi.fn(),
}));

vi.mock("@/components/modules/library/framework-review-panel", () => ({
  FrameworkReviewPanel: () => <div>Organization review controls</div>,
}));

vi.mock("@/components/modules/library/org-license-grant-panel", () => ({
  OrgLicenseGrantPanel: () => <div>License grant controls</div>,
}));

function renderLibrary(role: string) {
  return render(
    <OrganizationProvider
      capabilities={{ operator: "active" }}
      org={
        {
          id: "org-1",
          name: "Risk Council",
          suspended_at: null,
        } as never
      }
      orgId="org-1"
      role={role}
    >
      <OrgOperatorLibrary orgId="org-1" />
    </OrganizationProvider>,
  );
}

describe("OrgOperatorLibrary member access", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(listOrgLibrary).mockResolvedValue({
      data: {
        items: [
          {
            license_id: "license-1",
            framework_id: "framework-1",
            title: "Board Risk Operating System",
            version_at_grant: "1.0.0",
            current_version: "1.1.0",
            license_type: "team",
            source: "purchase",
            collection_id: null,
            status: "active",
            seats_used: 1,
            seats_total: 10,
            price: "499.00",
            currency: "USD",
            thumbnail_key: null,
            granted_at: "2026-07-19T00:00:00Z",
            expires_at: null,
            grant_count: 1,
          },
        ],
      },
      error: undefined,
      response: new Response(null, { status: 200 }),
    });
    vi.mocked(getExploreFrameworkDetail).mockResolvedValue({
      data: {
        artifacts: [
          {
            id: "artifact-1",
            name: "risk-playbook.pdf",
            file_size: 1024,
            mime_type: "application/pdf",
            created_at: "2026-07-19T00:00:00Z",
          },
        ],
      } as never,
      error: undefined,
      response: new Response(null, { status: 200 }),
    });
  });

  it("shows a granted Framework without admin-only management controls", async () => {
    renderLibrary("member");

    expect(
      await screen.findByText("Board Risk Operating System"),
    ).toBeInTheDocument();
    expect(
      await screen.findByRole("button", { name: /risk-playbook\.pdf/i }),
    ).toBeInTheDocument();
    expect(screen.queryByText("$499")).toBeNull();
    expect(screen.queryByText("Organization review controls")).toBeNull();
    expect(screen.queryByText("License grant controls")).toBeNull();
  });

  it("keeps review and license-grant management available to admins", async () => {
    renderLibrary("admin");

    expect(
      await screen.findByText("Organization review controls"),
    ).toBeInTheDocument();
    expect(screen.getByText("$499")).toBeInTheDocument();
    expect(screen.getByText("License grant controls")).toBeInTheDocument();
  });

  it("labels license status, source, and type in plain words", async () => {
    renderLibrary("member");

    await screen.findByText("Board Risk Operating System");
    // Scoped to the card: the "Active" filter segment shares the label.
    const status = within(screen.getByRole("article")).getByText("Active");
    expect(status.className).toContain("rounded-badge");
    expect(status.className).toContain("text-success");
    expect(screen.getByText("Purchased")).toBeInTheDocument();
    expect(screen.getByText("Team license")).toBeInTheDocument();
    expect(screen.queryByText(/status active/i)).not.toBeInTheDocument();
  });

  it("marks an expired license as expired", async () => {
    vi.mocked(listOrgLibrary).mockResolvedValue({
      data: {
        items: [
          {
            license_id: "license-2",
            framework_id: "framework-2",
            title: "Procurement Controls",
            version_at_grant: "1.0.0",
            current_version: "1.0.0",
            license_type: "single_user",
            source: "collection",
            collection_id: "col-1",
            status: "expired",
            seats_used: 0,
            seats_total: 1,
            price: "50000.00",
            currency: "NGN",
            thumbnail_key: null,
            granted_at: "2025-09-01T00:00:00Z",
            expires_at: "2026-09-01T00:00:00Z",
            grant_count: 0,
          },
        ],
      },
      error: undefined,
      response: new Response(null, { status: 200 }),
    });

    renderLibrary("member");

    await screen.findByText("Procurement Controls");
    expect(screen.getByText("Expired").className).toContain("rounded-badge");
    expect(screen.getByText("Collection")).toBeInTheDocument();
    expect(screen.getByText("Single user license")).toBeInTheDocument();
    expect(screen.getByText(/expired 1 sep 2026/i)).toBeInTheDocument();
  });

  const revokedItem = {
    license_id: "license-3",
    framework_id: "framework-3",
    title: "Vendor Due Diligence",
    version_at_grant: "1.0.0",
    current_version: "1.0.0",
    license_type: "team",
    source: "purchase",
    collection_id: null,
    status: "revoked",
    seats_used: 0,
    seats_total: 5,
    price: "75000.00",
    currency: "NGN",
    thumbnail_key: null,
    granted_at: "2025-09-01T00:00:00Z",
    expires_at: null,
    grant_count: 0,
  };

  it("asks for active licenses only by default", async () => {
    renderLibrary("admin");

    await screen.findByText("Board Risk Operating System");
    expect(listOrgLibrary).toHaveBeenCalledWith(
      expect.objectContaining({
        path: { org_id: "org-1" },
        query: expect.objectContaining({ include_inactive: false }),
      }),
    );
    expect(screen.getByRole("button", { name: "Active" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("includes expired and revoked licenses when All is selected", async () => {
    renderLibrary("admin");
    await screen.findByText("Board Risk Operating System");

    vi.mocked(listOrgLibrary).mockResolvedValue({
      data: { items: [revokedItem] },
      error: undefined,
      response: new Response(null, { status: 200 }),
    } as never);
    fireEvent.click(screen.getByRole("button", { name: "All" }));

    await waitFor(() =>
      expect(listOrgLibrary).toHaveBeenLastCalledWith(
        expect.objectContaining({
          query: expect.objectContaining({ include_inactive: true }),
        }),
      ),
    );
    expect(await screen.findByText("Vendor Due Diligence")).toBeInTheDocument();
  });

  it("offers no download or grant on an inactive license", async () => {
    vi.mocked(listOrgLibrary).mockResolvedValue({
      data: { items: [revokedItem] },
      error: undefined,
      response: new Response(null, { status: 200 }),
    } as never);

    renderLibrary("admin");

    await screen.findByText("Vendor Due Diligence");
    expect(screen.getByText("Revoked").className).toContain("rounded-badge");
    expect(screen.getByText("This license is no longer active.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /risk-playbook\.pdf/i })).toBeNull();
    expect(screen.queryByText("License grant controls")).toBeNull();
    expect(getExploreFrameworkDetail).not.toHaveBeenCalled();
  });
});
