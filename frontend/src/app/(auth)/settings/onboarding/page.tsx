/**
 * Authenticated first-time onboarding route.
 *
 * Prompts Phase 1 users to complete existing profile/KYC requirements while
 * preserving browse and preview access for marketplace discovery.
 */
import { AuthPageShell } from "@/components/modules/auth/auth-page-shell";
import { OnboardingPrompt } from "@/components/modules/auth/onboarding-prompt";

export default function OnboardingPage() {
  return (
    <AuthPageShell
      eyebrow="Account onboarding"
      summary="First-time users complete account identity and KYC before actions that require marketplace trust checks."
      title="Complete your account setup."
    >
      <OnboardingPrompt />
    </AuthPageShell>
  );
}
