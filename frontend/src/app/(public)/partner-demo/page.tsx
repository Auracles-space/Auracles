/**
 * Partner checkout demo route.
 *
 * Public sample of the buyer payment experience a Partner builds on their own
 * site with the Partner API. Not part of the authenticated app — it only needs
 * a Partner API key and a published framework id. Kept off `/checkout` so the
 * operator-only route guard does not gate this public demo.
 */
import { PartnerCheckoutDemo } from "@/components/modules/developer/partner-checkout-demo";
import { FooterCta } from "@/components/modules/landing/footer-cta";
import { MarketingNav } from "@/components/modules/landing/marketing-nav";

/**
 * Render the standalone Partner checkout demo page.
 */
export default function PartnerCheckoutDemoPage() {
  return (
    <div className="flex min-h-screen flex-col bg-background text-foreground">
      <MarketingNav />
      <PartnerCheckoutDemo />
      <FooterCta />
    </div>
  );
}
