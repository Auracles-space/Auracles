/**
 * Authenticated first-time onboarding route.
 *
 * Prompts Phase 1 users to complete existing profile/KYC requirements while
 * preserving browse and preview access for marketplace discovery.
 *
 * When the page is reached via the incomplete-user 403 interceptor, the
 * caller's `?next=<encoded-url>` + `?error_code=<code>` query params are
 * threaded through so:
 *   1. The eyebrow + summary copy mentions the specific blocker.
 *   2. After onboarding completes, the user can return to their intent path.
 */
import { OnboardingPrompt } from "@/components/modules/auth/onboarding-prompt";

type IncompleteErrorCode =
  | "kyc_required"
  | "email_unverified"
  | "profile_required"
  | "role_required";

type OnboardingPageProps = {
  searchParams?: Promise<{
    next?: string;
    error_code?: string;
  }>;
};

const COPY_BY_CODE: Record<
  IncompleteErrorCode,
  { eyebrow: string; summary: string }
> = {
  kyc_required: {
    eyebrow: "Verify your identity",
    summary:
      "Marketplace actions are gated by KYC. Finish identity checks to publish, upload, or download licensed Frameworks.",
  },
  email_unverified: {
    eyebrow: "Confirm your email",
    summary:
      "Confirm the email on file before marketplace actions unlock. Browse and preview stay open in the meantime.",
  },
  profile_required: {
    eyebrow: "Complete your profile",
    summary:
      "Add the profile details below so other operators and contributors can see who they are working with.",
  },
  role_required: {
    eyebrow: "Pick how you'll use Auracles",
    summary:
      "Choose Contributor, Operator, or both. Roles can be added later from settings.",
  },
};

const DEFAULT_COPY = {
  eyebrow: "Account onboarding",
  summary:
    "Browse and preview now. Finish identity checks before marketplace actions that require trust.",
};

/**
 * Render the onboarding page with optional context from the interceptor.
 *
 * @param props - Next.js searchParams payload.
 */
export default async function OnboardingPage({
  searchParams,
}: OnboardingPageProps) {
  const resolved = (await searchParams) ?? {};
  const errorCode = resolved.error_code as IncompleteErrorCode | undefined;
  const next = resolved.next;
  const copy =
    errorCode && errorCode in COPY_BY_CODE
      ? COPY_BY_CODE[errorCode]
      : DEFAULT_COPY;

  return (
    <main className="min-h-screen bg-background px-4 py-8 text-foreground md:px-8">
      <div className="mx-auto max-w-3xl">
        <header className="mb-8">
          <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
            {copy.eyebrow}
          </p>
          <h1 className="mt-2 font-heading text-3xl font-bold text-foreground">
            Complete your account setup
          </h1>
          <p className="mt-3 text-sm leading-6 text-foreground-muted">
            {copy.summary}
          </p>
          {next ? (
            <p className="mt-4 inline-flex max-w-full items-center gap-2 truncate rounded-control border border-border-default bg-surface-2 px-3 py-1.5 text-xs text-foreground-muted">
              <span className="font-medium text-foreground">Next stop:</span>
              <span className="truncate">{next}</span>
            </p>
          ) : null}
        </header>
        <section className="rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm">
          <OnboardingPrompt returnTo={next} />
        </section>
      </div>
    </main>
  );
}
