import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import ExploreDetailPage from "@/app/(public)/explore/[id]/page";
import {
  getExploreFrameworkDetail,
  getRelatedExploreFrameworks,
} from "@/lib/generated/sdk.gen";

vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

vi.mock("next/navigation", () => ({
  notFound: vi.fn(),
}));

vi.mock("@/components/modules/explore/framework-card", () => ({
  AttestationBadge: () => null,
  ReviewSummary: () => <span>reviews</span>,
}));

vi.mock("@/components/modules/explore/framework-license-cta", () => ({
  FrameworkLicenseCta: () => <div>license cta</div>,
}));

vi.mock("@/components/modules/attestation/request-attestation-link", () => ({
  RequestAttestationLink: () => null,
}));

vi.mock("@/components/modules/explore/preview-artifact-block", () => ({
  PreviewArtifactBlock: () => <div>preview</div>,
}));

vi.mock("@/components/modules/explore/related-frameworks", () => ({
  RelatedFrameworks: () => <div>related</div>,
}));

vi.mock("@/components/modules/reputation/reputation-badge", () => ({
  ReputationBadge: () => null,
}));

vi.mock("@/components/ui/back-button", () => ({
  BackButton: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  getExploreFrameworkDetail: vi.fn(),
  getRelatedExploreFrameworks: vi.fn(),
}));

vi.mock("@/lib/marketplace/api", () => ({
  configureServerMarketplaceClient: vi.fn(),
}));

describe("ExploreDetailPage org pricing", () => {
  it("shows the organizational price line only when the org tier is offered", async () => {
    vi.mocked(getExploreFrameworkDetail).mockResolvedValue({
      response: { ok: true },
      data: {
        id: "framework-1",
        contributor_id: "contributor-1",
        contributor_org_id: null,
        contributor_name: "Seller",
        contributor_slug: "seller",
        contributor_verification_level: null,
        contributor_reputation_score: null,
        title: "Org-ready Framework",
        description: "Description",
        version: "1.0.0",
        category: "framework",
        sector: "technology",
        industry: "software",
        function: "engineering",
        tags: ["governance"],
        jurisdiction: "us",
        complexity: 3,
        org_size: "mid_market",
        lifecycle_stage: "scale",
        price: "250.00",
        org_price: "900.00",
        currency: "USD",
        license_types: ["single_user", "organizational"],
        thumbnail_key: null,
        rarity_score: null,
        average_review_score: null,
        review_count: 0,
        attestation_badge: null,
        reputation: null,
        owned: false,
        published_at: null,
        preview_artifact_id: null,
        preview_url: null,
        artifacts: [],
        attestation_badges: [],
      },
    } as never);
    vi.mocked(getRelatedExploreFrameworks).mockResolvedValue({
      data: [],
    } as never);

    render(await ExploreDetailPage({ params: Promise.resolve({ id: "framework-1" }) }));

    expect(screen.getByText("Organizational")).toBeInTheDocument();
    expect(screen.getByText("$900")).toBeInTheDocument();
  });
});
