/**
 * Authenticated first-time onboarding route.
 *
 * Prompts Phase 1 users to complete existing profile/KYC requirements while
 * preserving browse and preview access for marketplace discovery.
 */
import { OnboardingPrompt } from "@/components/modules/auth/onboarding-prompt";

export default function OnboardingPage() {
  return (
    <main className="min-h-screen bg-background px-4 py-8 text-foreground md:px-8">
      <div className="mx-auto max-w-3xl">
        <header className="mb-8">
          <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
            Account onboarding
          </p>
          <h1 className="mt-2 font-heading text-3xl font-bold text-foreground">
            Complete your account setup
          </h1>
          <p className="mt-3 text-sm leading-6 text-foreground-muted">
            Browse and preview now. Finish identity checks before marketplace
            actions that require trust.
          </p>
        </header>
        <section className="rounded-[8px] border border-border-default bg-surface-1 p-5">
          <OnboardingPrompt />
        </section>
      </div>
    </main>
  );
}
