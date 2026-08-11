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

vi.mock("@/lib/auth/server-session", () => ({
  getVerifiedSessionHintFromCookies: vi.fn().mockResolvedValue(null),
}));

describe("landing sections render", () => {
  it("renders the hero with its headline copy", () => {
    render(<LandingHero />);
    expect(screen.getByText(/marketplace for operational frameworks/i)).toBeInTheDocument();
  });

  it("renders the role strip with contributor framing", () => {
    render(<RoleStrip />);
    expect(
      screen.getByText(/create recurring value from existing work/i),
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

  it("renders the trust grid contributor pillars", () => {
    render(<TrustGrid />);
    expect(screen.getByText(/publish your framework/i)).toBeInTheDocument();
  });

  it("renders the FAQ list", () => {
    render(<FaqList />);
    expect(screen.getByText(/what is a framework/i)).toBeInTheDocument();
  });

  it("renders the footer CTA with at least one heading", () => {
    render(<FooterCta />);
    expect(screen.getAllByRole("heading").length).toBeGreaterThan(0);
  });

  it("renders the marketing nav with navigation links", async () => {
    render(await MarketingNav());
    // Desktop and compact navs both render at every width, so each landmark is
    // asserted by its own accessible name rather than by role alone.
    expect(screen.getByRole("navigation", { name: "Primary" })).toBeInTheDocument();
    expect(
      screen.getByRole("navigation", { name: "Primary (compact)" }),
    ).toBeInTheDocument();
  });
});
