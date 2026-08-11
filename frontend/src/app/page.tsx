/**
 * Marketing landing page.
 *
 * Composes the hero, the loop explainer, role panels, the entry ladder,
 * license options, FAQ, and the closing waitlist CTA.
 * Server Component — fully static, no client JS required.
 *
 * Phase 0 foundation status surface lives at `/status`.
 */
import { FaqList } from "@/components/modules/landing/faq-list";
import { FooterCta } from "@/components/modules/landing/footer-cta";
import { HowItWorks } from "@/components/modules/landing/how-it-works";
import { LandingHero } from "@/components/modules/landing/landing-hero";
import { MarketingNav } from "@/components/modules/landing/marketing-nav";
import { PricingStrip } from "@/components/modules/landing/pricing-strip";
import { RoleStrip } from "@/components/modules/landing/role-strip";
import { TrustGrid } from "@/components/modules/landing/trust-grid";

export default function Home() {
  return (
    <div className="min-h-screen bg-background text-foreground">
      <MarketingNav />
      <main id="main">
        <LandingHero />
        <HowItWorks />
        <RoleStrip />
        <TrustGrid />
        <PricingStrip />
        <FaqList />
      </main>
      <FooterCta />
    </div>
  );
}

