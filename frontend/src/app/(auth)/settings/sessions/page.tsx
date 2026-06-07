/**
 * Authenticated session settings route.
 *
 * Middleware requires a signed session hint before this page renders; API
 * calls still use the generated client with bearer access tokens.
 */
import { AuthPageShell } from "@/components/modules/auth/auth-page-shell";
import { SessionList } from "@/components/modules/settings/session-list";

export default function SessionsSettingsPage() {
  return (
    <AuthPageShell
      eyebrow="Session security"
      summary="Review where your account is active and revoke refresh-token sessions that should no longer have access."
      title="Manage active browser sessions."
    >
      <SessionList autoload />
    </AuthPageShell>
  );
}
