/**
 * Phase 1 onboarding prompt.
 *
 * Prompts newly authenticated users to complete the profile/KYC work currently
 * available in Phase 1 while making it clear that browsing and framework
 * previews remain available.
 */
import Link from "next/link";

const steps = [
  {
    body: "Your registered display name is the Phase 1 profile baseline. Expanded public profile fields arrive in the settings phase.",
    title: "Complete your profile",
  },
  {
    body: "A quick, secure check with our verification partner — about two minutes with a government ID. Your documents stay with Persona, never stored on Auracles.",
    title: "Verify your identity",
  },
];

type OnboardingPromptProps = {
  /**
   * Path the user attempted before being redirected to onboarding. Forwarded
   * to the KYC link as `?next=` so the user can resume their intent once
   * verification completes.
   */
  returnTo?: string;
};

/**
 * Render the first-time user completion prompt.
 *
 * @param props - Optional return-to hint from the incomplete-user interceptor.
 */
export function OnboardingPrompt({ returnTo }: OnboardingPromptProps = {}) {
  const kycHref = returnTo
    ? `/settings/kyc?next=${encodeURIComponent(returnTo)}`
    : "/settings/kyc";

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
            className="rounded-[20px] border border-border-strong bg-surface-2 p-4 shadow-sm"
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
        <Link
          className="inline-flex min-h-12 w-full items-center justify-center rounded-control border-transparent bg-foreground px-4 py-2 text-sm font-semibold text-background transition hover:bg-foreground/90 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-foreground active:scale-[0.98] shadow-md"
          href={kycHref}
        >
          Verify identity
        </Link>
        <Link
          className="inline-flex min-h-12 w-full items-center justify-center rounded-control border-2 border-foreground bg-transparent px-4 py-2 text-sm font-semibold text-foreground transition hover:bg-foreground hover:text-background focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-foreground"
          href="/explore"
        >
          Browse frameworks
        </Link>
      </div>
    </div>
  );
}
