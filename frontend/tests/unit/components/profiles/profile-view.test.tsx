import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ProfileView } from "@/components/modules/profiles/profile-view";
import type {
  ExploreFrameworkCard,
  PublicProfileResponse,
} from "@/lib/generated/types.gen";

const framework: ExploreFrameworkCard = {
  attestation_badge: null,
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
  license_types: ["single_user"],
  org_size: "mid_market",
  owned: false,
  price: "250.00",
  published_at: "2026-06-09T00:00:00Z",
  rarity_score: "0.82",
  review_count: 2,
  sector: "private_equity",
  tags: ["diligence"],
  thumbnail_key: null,
  title: "Diligence Control Playbook",
  version: "1.0.0",
};

/**
 * A fully-populated profile that exercises every optional section so a single
 * render covers the bulk of the presentation branches.
 */
const fullProfile: PublicProfileResponse = {
  id: "00000000-0000-4000-8000-000000000099",
  display_name: "Mara Okafor",
  avatar_url: "https://cdn.auracles.space/avatars/a.png",
  banner_url: "https://cdn.auracles.space/banners/b.png",
  headline: "Governance systems architect",
  bio: "Builds diligence controls for private equity operators.",
  location: "Lagos, NG",
  website: "https://maraokafor.example",
  specializations: ["Governance", "Diligence"],
  links: [
    { label: "Portfolio", url: "https://maraokafor.example/work" },
    { label: "Unsafe", url: "javascript:alert(1)" },
  ],
  social_links: [
    { platform: "github", url: "https://github.com/mara" },
    { platform: "x", url: "javascript:alert(1)" },
  ],
  featured: [
    { framework_id: framework.id, framework },
    {
      title: "Case study",
      description: "How we cut diligence time in half.",
      url: "https://maraokafor.example/case",
    },
    { title: "No link spotlight", description: null, url: null },
  ],
  experience: [
    {
      title: "Principal",
      company: "Auracles",
      start: "2021",
      end: "",
      current: true,
      description: "Led the controls practice.",
    },
  ],
  education: [
    {
      school: "Unilag",
      degree: "BSc",
      field: "Economics",
      start_year: 2010,
      end_year: 2014,
    },
  ],
  verified_credentials: [
    {
      title: "CFA",
      issuer: "CFA Institute",
      credential_type: "certification",
      issued_date: "2019-01-01",
      expires_date: "2030-01-01",
      expired: false,
    },
  ],
  stats: {
    frameworks_published: 3,
    reviews_received: 2,
    average_rating: 4.5,
  },
  roles: ["contributor", "attestor"],
  kyc_verified: true,
  is_deactivated: false,
};

describe("ProfileView", () => {
  it("renders identity, headline, badges and every populated section", () => {
    render(<ProfileView profile={fullProfile} headerAction={<button>Edit</button>} />);

    expect(
      screen.getByRole("heading", { level: 1, name: "Mara Okafor" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Governance systems architect")).toBeInTheDocument();
    expect(screen.getAllByText("Verified").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Edit" })).toBeInTheDocument();

    // Section headings render only when their list is non-empty.
    expect(screen.getByRole("heading", { name: "Featured" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Links" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Experience" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Education" })).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Verified credentials" }),
    ).toBeInTheDocument();
  });

  it("links the website and a safe portfolio link, dropping unsafe schemes", () => {
    render(<ProfileView profile={fullProfile} />);

    expect(screen.getByRole("link", { name: "Visit website" })).toHaveAttribute(
      "href",
      "https://maraokafor.example",
    );
    expect(screen.getByRole("link", { name: /Portfolio/ })).toHaveAttribute(
      "href",
      "https://maraokafor.example/work",
    );
    // The javascript: link is dropped, so no link is rendered for it.
    expect(screen.queryByText("Unsafe")).not.toBeInTheDocument();
  });

  it("renders social icons for safe links and drops unsafe schemes", () => {
    render(<ProfileView profile={fullProfile} />);

    const github = screen.getByRole("link", { name: "GitHub" });
    expect(github).toHaveAttribute("href", "https://github.com/mara");
    // The javascript: X link is dropped, so no X social link is rendered.
    expect(screen.queryByRole("link", { name: "X" })).not.toBeInTheDocument();
  });

  it("renders a passed Framework as its live card alongside free-form spotlights", () => {
    render(<ProfileView profile={fullProfile} />);

    expect(
      screen.getByRole("heading", { name: "Diligence Control Playbook" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Case study")).toBeInTheDocument();
    expect(screen.getByText("No link spotlight")).toBeInTheDocument();
  });

  it("omits optional sections and the verified seal for a minimal profile", () => {
    const minimal: PublicProfileResponse = {
      id: "00000000-0000-4000-8000-000000000001",
      display_name: "Quiet User",
      kyc_verified: false,
    };

    render(<ProfileView profile={minimal} />);

    expect(
      screen.getByRole("heading", { level: 1, name: "Quiet User" }),
    ).toBeInTheDocument();
    expect(screen.queryByText("Verified")).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Featured" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Links" })).not.toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: "Visit website" }),
    ).not.toBeInTheDocument();
  });

  it("shows the Read-only badge for a deactivated account", () => {
    render(
      <ProfileView
        profile={{ ...fullProfile, is_deactivated: true }}
      />,
    );

    expect(screen.getByText("Read-only")).toBeInTheDocument();
  });

  it("renders a Contributor's published Frameworks section", () => {
    render(<ProfileView profile={fullProfile} frameworks={[framework]} />);

    expect(
      screen.getByRole("heading", { name: "Published Frameworks" }),
    ).toBeInTheDocument();
  });
});
