import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AttestorApplicationTab } from "@/components/modules/organizations/attestor/attestor-application-tab";
import {
  getOrgAttestorApplication,
  listMembersV1OrgsOrgIdMembersGet as listMembers,
} from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => {
  return {
    configureBrowserClient: vi.fn(),
    describeGeneratedError: vi.fn(() => "err"),
    getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer t" })),
  };
});
vi.mock("@/components/modules/organizations/organization-context", () => ({
  useOrganization: () => ({ orgId: "org-1", role: "owner" }),
}));
vi.mock("@/lib/generated/sdk.gen", () => ({
  getOrgAttestorApplication: vi.fn(),
  listMembersV1OrgsOrgIdMembersGet: vi.fn(),
}));

const ok = <T,>(data: T) => ({
  data, error: undefined,
  request: new Request("http://t"), response: new Response(null, { status: 200 }),
});

const notFound = () => ({
  data: undefined,
  error: { detail: "Org attestor application not found." },
  request: new Request("http://t"),
  response: new Response(null, { status: 404 }),
});

describe("AttestorApplicationTab", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(listMembers).mockResolvedValue(
      ok({ members: [] }) as never,
    );
  });

  it("renders the owner's steps with the review stage pinned above", async () => {
    vi.mocked(getOrgAttestorApplication).mockResolvedValue(
      ok({ status: "submitted", admin_feedback: null }) as never,
    );
    render(<AttestorApplicationTab />);

    expect(
      await screen.findByRole("heading", { name: "Application in review" }),
    ).toBeInTheDocument();
    expect(
      screen.getAllByRole("button", { name: /^Step \d/ }).map((b) => b.getAttribute("aria-label")),
    ).toEqual([
      "Step 1: Details",
      "Step 2: Undertakings",
      "Step 3: Tax document",
      "Step 4: Payout account",
      "Step 5: Trial member",
      "Step 6: Submit, complete",
    ]);
    // Review, trial, approval and activation are admin-driven: a track in the
    // banner, never steps.
    expect(screen.getByText("Activation").closest("li")).not.toBeNull();
  });

  it("does not carry a KYB step of its own", async () => {
    // Business verification happens on the organization before it can open an
    // application at all, so a KYB step here would be permanently complete and
    // would imply the flow still does the checking.
    vi.mocked(getOrgAttestorApplication).mockResolvedValue(
      ok({ status: "submitted", admin_feedback: null }) as never,
    );
    render(<AttestorApplicationTab />);

    await screen.findByRole("navigation", { name: "Application steps" });
    expect(screen.queryByRole("button", { name: /KYB|verification/i })).toBeNull();
    expect(screen.queryByRole("heading", { name: /KYB verification/i })).toBeNull();
  });

  it("renders the unstarted Apply gate when no application exists (404)", async () => {
    vi.mocked(getOrgAttestorApplication).mockResolvedValue(notFound() as never);
    render(<AttestorApplicationTab />);
    // 404 = no application yet, not an error: show the gates so the owner can apply.
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: /Apply/i })).toBeInTheDocument(),
    );
    expect(
      screen.queryByRole("heading", { name: /Failed to load application/i }),
    ).not.toBeInTheDocument();
  });
});
