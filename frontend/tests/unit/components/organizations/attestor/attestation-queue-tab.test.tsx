import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AttestationQueueTab } from "../../../../../src/components/modules/organizations/attestor/attestation-queue-tab";
import { listOrgAttestationsV1OrgsOrgIdAttestationsGet } from "../../../../../src/lib/generated/sdk.gen";

const { push } = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("../../../../../src/lib/auth/form-client", () => ({
  describeGeneratedError: vi.fn(() => "err"),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer t" })),
}));
vi.mock("../../../../../src/components/modules/organizations/organization-context", () => ({
  useOrganization: () => ({ orgId: "org-1", role: "owner" }),
}));
vi.mock("../../../../../src/lib/generated/sdk.gen", () => ({ 
  listOrgAttestationsV1OrgsOrgIdAttestationsGet: vi.fn() 
}));
const ok = <T,>(d: T) => ({ data: d, error: undefined, request: new Request("http://t"), response: new Response(null, { status: 200 }) });

describe("AttestationQueueTab", () => {
  beforeEach(() => vi.clearAllMocks());

  it("lists active attestations", async () => {
    vi.mocked(listOrgAttestationsV1OrgsOrgIdAttestationsGet).mockResolvedValueOnce(
      ok({ attestations: [
        { id: "att-1", target_type: "framework", target_id: "fw-1", target_title: "Growth Playbook", review_type: "standard", status: "in_review", reviewing_member_id: "mem-1", reviewing_member_name: "Mem One", outcome: null, accepted_at: null, completion_due_at: null }
      ] })
    );
    render(<AttestationQueueTab />);
    await waitFor(() => expect(screen.getByText(/Growth Playbook/)).toBeInTheDocument());
    expect(screen.getByText(/in review/i)).toBeInTheDocument();
    // role "owner" ⇒ admin view exposes the assigned reviewer name.
    expect(screen.getByText(/Mem One/)).toBeInTheDocument();
  });
});
