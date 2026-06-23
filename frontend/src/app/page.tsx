/**
 * Marketing landing page.
 *
 * Composes the hero, role panels, trust grid, pricing, FAQ, and closing CTA.
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

const isWaitlistMode = process.env.NEXT_PUBLIC_WAITLIST_MODE !== "false";

export default function Home() {
  return (
    <div className="min-h-screen bg-background text-foreground">
      <MarketingNav />
      <LandingHero />
      <HowItWorks />
      <RoleStrip />
      <TrustGrid />
      {!isWaitlistMode && <PricingStrip />}
      <FaqList />
      <FooterCta />
    </div>
  );
}

