import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AttestorOrgCard } from "@/components/modules/attestation/directory/attestor-org-card";

describe("AttestorOrgCard", () => {
  it("renders org identity and completed count, never member identities", () => {
    render(<AttestorOrgCard org={{
      org_id: "org-1", name: "Audit Ltd", slug: "audit-ltd",
      verification_level: "verified", completed_count: 12, member_count: 4,
      sectors: ["cybersecurity"],
      reviewing_member_name: "SHOULD-NOT-RENDER",
    } as never} />);
    
    expect(screen.getByText("Audit Ltd")).toBeInTheDocument();
    expect(screen.getByText(/12/)).toBeInTheDocument();
    expect(screen.queryByText(/SHOULD-NOT-RENDER/)).toBeNull();
  });
});
