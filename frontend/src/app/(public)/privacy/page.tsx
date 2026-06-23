import { MarketingNav } from "@/components/modules/landing/marketing-nav";
import { FooterCta } from "@/components/modules/landing/footer-cta";

export const metadata = {
  title: "Privacy Policy - Auracles",
  description: "Learn how Auracles collects, processes, and protects your personal data.",
};

export default function PrivacyPage() {
  return (
    <div className="min-h-screen bg-background text-foreground flex flex-col">
      <MarketingNav />
      <main className="flex-1 mx-auto w-full max-w-[800px] px-6 py-12 md:py-20">
        <article className="space-y-8 font-sans">
          <div className="border-b border-border-default pb-6">
            <p className="text-xs font-semibold uppercase tracking-wider text-accent">Privacy</p>
            <h1 className="mt-2 font-heading text-3xl font-extrabold tracking-tight text-foreground sm:text-4xl">
              Privacy Policy
            </h1>
            <p className="mt-2 text-sm text-foreground-muted">Version 1.0 • Last updated June 2026</p>
          </div>

          <div className="space-y-6 text-base leading-7 text-foreground-muted">
            <section className="space-y-3">
              <h2 className="font-heading text-xl font-bold text-foreground">1. Introduction</h2>
              <p>
                At Auracles, we respect your privacy and are committed to protecting your personal data. This Privacy Policy details
                how we collect, use, store, and process your personal information when you use our marketplace platform and related services.
              </p>
            </section>

            <hr className="border-border-default" />

            <section className="space-y-3">
              <h2 className="font-heading text-xl font-bold text-foreground">2. Information We Collect</h2>
              <p>We may collect and process the following categories of information:</p>
              <ul className="list-disc pl-5 space-y-1">
                <li><strong>Account Credentials:</strong> Email address, password, and authentication tokens.</li>
                <li><strong>Identity Data:</strong> Full name, verified professional details, and government-issued identification for KYC compliance.</li>
                <li><strong>Financial Data:</strong> Bank account, payment card, or payout billing details processed securely through our payment provider partners.</li>
                <li><strong>Usage Data:</strong> Logging information regarding framework uploads, downloads, views, and transaction histories.</li>
              </ul>
            </section>

            <hr className="border-border-default" />

            <section className="space-y-3">
              <h2 className="font-heading text-xl font-bold text-foreground">3. How We Use Your Data</h2>
              <p>We utilize collected information to support operational compliance and run the marketplace, specifically to:</p>
              <ul className="list-disc pl-5 space-y-1">
                <li>Create and secure your user account.</li>
                <li>Facilitate transactions, licensings, and payouts between Contributors and Operators.</li>
                <li>Verify identities and maintain the platform trust floor (KYC checking).</li>
                <li>Audit and log platform actions for GDPR and compliance transparency.</li>
              </ul>
            </section>

            <hr className="border-border-default" />

            <section className="space-y-3">
              <h2 className="font-heading text-xl font-bold text-foreground">4. Contact Information</h2>
              <p>If you have any questions about this Privacy Policy or wish to request data deletion/export, please reach out to us:</p>
              <div className="space-y-2 bg-surface-2 p-6 rounded-card border border-border-default text-sm">
                <p className="font-medium text-foreground">Auracles Privacy Team</p>
                <p>
                  Email:{" "}
                  <a href="mailto:admin@auracles.space" className="text-accent hover:underline font-semibold">
                    admin@auracles.space
                  </a>
                </p>
              </div>
            </section>
          </div>
        </article>
      </main>
      <FooterCta />
    </div>
  );
}
