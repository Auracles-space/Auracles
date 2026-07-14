import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AttestorOrgProfile } from "@/components/modules/attestation/directory/attestor-org-profile";

describe("AttestorOrgProfile", () => {
  it("renders profile fields and no member identity appears", () => {
    render(<AttestorOrgProfile org={{
      org_id: "org-1", name: "Audit Ltd", slug: "audit-ltd",
      verification_level: 2, completed_attestations: 12, member_count: 4,
      sectors: ["technology"], functions: [], jurisdictions: [],
      reputation: null,
      // @ts-expect-error member identity must never reach a public surface
      reviewing_member_name: "SHOULD-NOT-RENDER",
    }} />);

    expect(screen.getByText("Audit Ltd")).toBeInTheDocument();
    expect(screen.getByText(/12/)).toBeInTheDocument();
    expect(screen.queryByText(/SHOULD-NOT-RENDER/)).toBeNull();
  });
});
