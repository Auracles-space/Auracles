import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { FaqList } from "@/components/modules/landing/faq-list";
import { FooterCta } from "@/components/modules/landing/footer-cta";
import { HowItWorks } from "@/components/modules/landing/how-it-works";
import { LandingHero } from "@/components/modules/landing/landing-hero";
import { MarketingNav } from "@/components/modules/landing/marketing-nav";
import { PricingStrip } from "@/components/modules/landing/pricing-strip";
import { RoleStrip } from "@/components/modules/landing/role-strip";
import { TrustGrid } from "@/components/modules/landing/trust-grid";

vi.mock("@/components/ui/theme-toggle", () => ({
  ThemeToggle: () => <button type="button">Toggle theme</button>,
}));

describe("landing sections render", () => {
  it("renders the hero with its headline copy", () => {
    render(<LandingHero />);
    expect(screen.getByText(/performance across frameworks/i)).toBeInTheDocument();
  });

  it("renders the role strip with contributor framing", () => {
    render(<RoleStrip />);
    expect(
      screen.getByText(/earn from the playbooks you already run/i),
    ).toBeInTheDocument();
  });

  it("renders the pricing strip tiers", () => {
    render(<PricingStrip />);
    expect(screen.getByText(/one named operator/i)).toBeInTheDocument();
  });

  it("renders the how-it-works role flow", () => {
    render(<HowItWorks />);
    expect(screen.getAllByRole("heading").length).toBeGreaterThan(0);
  });

  it("renders the trust grid enforcement seams", () => {
    render(<TrustGrid />);
    expect(screen.getByText(/kyc at the boundary/i)).toBeInTheDocument();
  });

  it("renders the FAQ list", () => {
    render(<FaqList />);
    expect(screen.getByText(/what is a framework/i)).toBeInTheDocument();
  });

  it("renders the footer CTA with at least one heading", () => {
    render(<FooterCta />);
    expect(screen.getAllByRole("heading").length).toBeGreaterThan(0);
  });

  it("renders the marketing nav with navigation links", () => {
    render(<MarketingNav />);
    expect(screen.getByRole("navigation")).toBeInTheDocument();
  });
});
