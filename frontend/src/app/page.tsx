/**
 * Marketing landing page.
 *
 * Composes the hero, the loop explainer, role panels, the entry ladder,
 * license options, FAQ, and the closing waitlist CTA.
 * Server Component, no client JS required. Revalidated hourly rather than
 * fully static: the contributor section carries live demand, and the demand
 * rollup runs hourly, so anything shorter would re-render for no new data.
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
import { loadDemandMap } from "@/lib/marketplace/explore-read-model";

export const revalidate = 3600;

export default async function Home() {
  const { demand } = await loadDemandMap();

  return (
    <div className="min-h-screen bg-background text-foreground">
      <MarketingNav />
      <main id="main">
        <LandingHero />
        <HowItWorks />
        <RoleStrip />
        <TrustGrid demandTerms={demand?.terms ?? null} />
        <PricingStrip />
        <FaqList />
      </main>
      <FooterCta />
    </div>
  );
}

