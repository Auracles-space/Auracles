/**
 * Phase 1 onboarding prompt.
 *
 * Prompts newly authenticated users to complete the profile/KYC work currently
 * available in Phase 1 while making it clear that browsing and framework
 * previews remain available.
 */
const steps = [
  {
    body: "Your registered display name is the Phase 1 profile baseline. Expanded public profile fields arrive in the settings phase.",
    title: "Complete your profile",
  },
  {
    body: "Upload a private identity document so the account is ready for marketplace actions that require verification.",
    title: "Submit identity verification",
  },
];

/**
 * Render the first-time user completion prompt.
 */
export function OnboardingPrompt() {
  return (
    <div className="space-y-6">
      <div>
        <h2 className="font-heading text-xl font-semibold text-foreground">
          Account completion
        </h2>
        <p className="mt-2 text-sm leading-6 text-foreground-muted">
          You can browse and preview frameworks now. Complete these items before
          marketplace actions that require trust checks.
        </p>
      </div>

      <div className="space-y-3">
        {steps.map((step) => (
          <article
            className="rounded-card border border-border-strong bg-surface-3 p-4"
            key={step.title}
          >
            <h3 className="font-heading text-sm font-semibold text-foreground">
              {step.title}
            </h3>
            <p className="mt-2 text-sm leading-6 text-foreground-muted">
              {step.body}
            </p>
          </article>
        ))}
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <a
          className="inline-flex min-h-11 w-full items-center justify-center rounded-control border border-brand bg-brand px-4 py-2 text-sm font-semibold text-white transition hover:bg-brand-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand active:scale-[0.98]"
          href="/settings/kyc"
        >
          Start KYC
        </a>
        <a
          className="inline-flex min-h-11 w-full items-center justify-center rounded-control border border-border-strong bg-transparent px-4 py-2 text-sm font-semibold text-foreground transition hover:bg-surface-1 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand"
          href="/explore"
        >
          Browse frameworks
        </a>
      </div>
    </div>
  );
}
