import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  AttestationBadge,
  CollectionCard,
  FrameworkCard,
} from "@/components/modules/explore/framework-card";
import type {
  ExploreCollectionCard,
  ExploreFrameworkCard,
} from "@/lib/generated/types.gen";

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

const collection: ExploreCollectionCard = {
  bundle_price: "700.00",
  contributor_id: "00000000-0000-4000-8000-000000000014",
  contributor_name: "Mara Okafor",
  created_at: "2026-06-09T00:00:00Z",
  currency: "USD",
  description: "A bundled operating system for diligence controls.",
  id: "00000000-0000-4000-8000-000000000020",
  item_type: "collection",
  member_count: 3,
  member_price_sum: "900.00",
  members: [
    {
      category: "playbook",
      currency: "USD",
      framework_id: "00000000-0000-4000-8000-000000000021",
      price: "250.00",
      thumbnail_key: null,
      title: "Diligence Control Playbook",
      version: "1.0.0",
    },
  ],
  savings_amount: "200.00",
  savings_percent: "22.22",
  title: "Diligence Control Collection",
  updated_at: "2026-06-09T00:00:00Z",
};

describe("FrameworkCard", () => {
  it("links the Contributor name to the public Contributor profile", () => {
    render(<FrameworkCard framework={framework} />);

    expect(screen.getByRole("link", { name: "Mara Okafor" })).toHaveAttribute(
      "href",
      "/explore/contributors/00000000-0000-4000-8000-000000000014",
    );
  });

  it("links the Preview action to the Framework detail page", () => {
    render(<FrameworkCard framework={framework} />);

    expect(
      screen.getByRole("link", { name: /preview diligence control playbook/i }),
    ).toHaveAttribute("href", "/explore/00000000-0000-4000-8000-000000000013");
  });
});

describe("CollectionCard", () => {
  it("renders collection savings and links to collection detail", () => {
    render(<CollectionCard collection={collection} />);

    expect(
      screen.getByRole("link", { name: "Diligence Control Collection" }),
    ).toHaveAttribute(
      "href",
      "/explore/collections/00000000-0000-4000-8000-000000000020",
    );
    expect(screen.getByText("3 frameworks")).toBeInTheDocument();
    expect(screen.getByText("Save $200")).toBeInTheDocument();
    expect(screen.getByText("22.22% off")).toBeInTheDocument();
  });
});

describe("AttestationBadge", () => {
  it("renders conditional attestations distinctly with report count", () => {
    render(<AttestationBadge badge={framework.attestation_badge!} />);

    expect(screen.getByText(/Conditional: Conditional/)).toBeInTheDocument();
    expect(screen.getByText(/2 reports/)).toBeInTheDocument();
  });
});
