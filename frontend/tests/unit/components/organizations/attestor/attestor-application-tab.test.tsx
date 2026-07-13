import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AttestorApplicationTab } from "@/components/modules/organizations/attestor/attestor-application-tab";
import { getOrgAttestorApplication } from "@/lib/generated/sdk.gen";

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
vi.mock("@/lib/generated/sdk.gen", () => ({ getOrgAttestorApplication: vi.fn() }));

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
  beforeEach(() => vi.clearAllMocks());

  it("renders the 8 activation gates with per-gate status", async () => {
    vi.mocked(getOrgAttestorApplication).mockResolvedValue(
      ok({ status: "submitted", kyb_verified_at: "2026-07-01T00:00:00Z", admin_feedback: null }) as never,
    );
    render(<AttestorApplicationTab />);
    await waitFor(() => expect(screen.getByRole("heading", { name: /KYB verification/i })).toBeInTheDocument());
    expect(screen.getByRole("heading", { name: /Apply/i })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Trial attestation/i })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Activation/i })).toBeInTheDocument();
    // KYB gate shows verified
    expect(screen.getByText(/verified/i)).toBeInTheDocument();
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
