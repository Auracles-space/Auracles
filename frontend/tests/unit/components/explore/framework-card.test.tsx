import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  AttestationBadge,
  FrameworkCard,
} from "@/components/modules/explore/framework-card";
import type { ExploreFrameworkCard } from "@/lib/generated/types.gen";

const framework: ExploreFrameworkCard = {
  attestation_badge: {
    attestation_count: 2,
    id: "00000000-0000-4000-8000-000000000021",
    issued_at: "2026-06-11T00:00:00Z",
    outcome: "conditional",
    report_key: "attestation-reports/report.pdf",
    status: "conditionally_attested",
  },
  average_review_score: "4.50",
  category: "playbook",
  complexity: 3,
  contributor_id: "00000000-0000-4000-8000-000000000014",
  contributor_name: "Mara Okafor",
  currency: "USD",
  description: "Operator-ready controls for diligence workstreams.",
  function: "governance",
  id: "00000000-0000-4000-8000-000000000013",
  industry: "fund_management",
  jurisdiction: "US",
  lifecycle_stage: "growth",
  license_types: ["single_user", "team"],
  org_size: "mid_market",
  owned: false,
  price: "250.00",
  published_at: "2026-06-09T00:00:00Z",
  rarity_score: "0.82",
  review_count: 2,
  sector: "private_equity",
  tags: ["diligence", "controls"],
  thumbnail_key: null,
  title: "Diligence Control Playbook",
  version: "1.0.0",
};

describe("FrameworkCard", () => {
  it("links the Contributor name to the public Contributor profile", () => {
    render(<FrameworkCard framework={framework} />);

    expect(screen.getByRole("link", { name: "Mara Okafor" })).toHaveAttribute(
      "href",
      "/explore/contributors/00000000-0000-4000-8000-000000000014",
    );
  });
});

describe("AttestationBadge", () => {
  it("renders conditional attestations distinctly with report count", () => {
    render(<AttestationBadge badge={framework.attestation_badge!} />);

    expect(screen.getByText(/Conditional: Conditional/)).toBeInTheDocument();
    expect(screen.getByText(/2 reports/)).toBeInTheDocument();
  });
});
