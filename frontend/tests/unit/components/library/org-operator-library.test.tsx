/**
 * Organization shared-library access tests.
 *
 * Verifies that granted members can consume Frameworks without receiving
 * organization-admin review or license-allocation controls.
 */
import { render, screen } from "@testing-library/react";
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
    const status = screen.getByText("Active");
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
});
