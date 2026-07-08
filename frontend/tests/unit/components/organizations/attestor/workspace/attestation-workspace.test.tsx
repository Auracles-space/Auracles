import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AttestationWorkspace } from "@/components/modules/organizations/attestor/workspace/attestation-workspace";
import { getAttestation, listOrgAttestations } from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: vi.fn(() => "err"),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer t" })),
}));
vi.mock("@/components/modules/organizations/organization-context", () => ({
  useOrganization: () => ({ orgId: "org-1", role: "member", memberId: "mem-1" }),
}));
vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), refresh: vi.fn() }))
}));
vi.mock("@/lib/generated/sdk.gen", () => ({
  getAttestation: vi.fn(),
  listOrgAttestations: vi.fn(),
  startAttestationReview: vi.fn(),
  giveAttestationConsent: vi.fn(),
  ackAttestationContent: vi.fn(),
}));
const ok = <T,>(d: T) => ({ data: d, error: undefined, request: new Request("http://t"), response: new Response(null, { status: 200 }) });

describe("AttestationWorkspace", () => {
  beforeEach(() => vi.clearAllMocks());

  it("offers Start review to the assigned reviewing member before review starts", async () => {
    vi.mocked(getAttestation).mockResolvedValue(
      ok({ id: "att-1", status: "assigned" }) as never,
    );
    vi.mocked(listOrgAttestations).mockResolvedValue(
      ok([{ id: "att-1", status: "assigned", reviewing_member_id: "mem-1", review_started_at: null }]) as never,
    );
    render(<AttestationWorkspace orgId="org-1" attestationId="att-1" />);
    await waitFor(() => expect(screen.getByRole("button", { name: /start review/i })).toBeEnabled());
  });

  it("is read-only for an owner who is not the reviewing member", async () => {
    vi.mocked(getAttestation).mockResolvedValue(
      ok({ id: "att-1", status: "in_review" }) as never,
    );
    vi.mocked(listOrgAttestations).mockResolvedValue(
      ok([{ id: "att-1", status: "in_review", reviewing_member_id: "mem-9", review_started_at: "2026-07-05T00:00:00Z" }]) as never,
    );
    render(<AttestationWorkspace orgId="org-1" attestationId="att-1" />);
    await waitFor(() => screen.getByText(/att-1/));
    expect(screen.queryByRole("button", { name: /start review/i })).toBeNull();
  });
});
