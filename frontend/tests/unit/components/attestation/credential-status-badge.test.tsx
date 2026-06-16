import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CredentialStatusBadge } from "@/components/modules/attestation/credential-status-badge";

describe("CredentialStatusBadge", () => {
  it("renders the verified label with success tokens", () => {
    render(<CredentialStatusBadge status="verified" expired={false} />);
    const badge = screen.getByText("Verified");
    expect(badge).toBeInTheDocument();
    expect(badge.className).toContain("text-success");
  });

  it("renders the pending label with warning tokens", () => {
    render(<CredentialStatusBadge status="pending" expired={false} />);
    const badge = screen.getByText("Pending review");
    expect(badge).toBeInTheDocument();
    expect(badge.className).toContain("text-warning");
  });

  it("renders the rejected label with error tokens", () => {
    render(<CredentialStatusBadge status="rejected" expired={false} />);
    const badge = screen.getByText("Rejected");
    expect(badge).toBeInTheDocument();
    expect(badge.className).toContain("text-error");
  });

  it("renders the unverified label with muted tokens", () => {
    render(<CredentialStatusBadge status="unverified" expired={false} />);
    const badge = screen.getByText("Not submitted");
    expect(badge).toBeInTheDocument();
    expect(badge.className).toContain("text-foreground-muted");
  });

  it("shows an Expired pill when verified and expired", () => {
    render(<CredentialStatusBadge status="verified" expired={true} />);
    expect(screen.getByText("Verified")).toBeInTheDocument();
    expect(screen.getByText("Expired")).toBeInTheDocument();
  });

  it("does not show an Expired pill when not verified even if expired", () => {
    render(<CredentialStatusBadge status="unverified" expired={true} />);
    expect(screen.queryByText("Expired")).not.toBeInTheDocument();
  });
});
