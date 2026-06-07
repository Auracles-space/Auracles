/**
 * Authenticated 2FA setup route.
 *
 * Middleware requires a valid session hint before this page renders.
 */
import { AuthPageShell } from "@/components/modules/auth/auth-page-shell";
import { TotpSetupPanel } from "@/components/modules/auth/totp-setup-panel";

export default function TotpSetupPage() {
  return (
    <AuthPageShell
      eyebrow="Account protection"
      summary="Two-factor authentication is required before sensitive account and payout operations."
      title="Add an authenticator app to your account."
    >
      <TotpSetupPanel />
    </AuthPageShell>
  );
}
