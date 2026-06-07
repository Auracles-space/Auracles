/**
 * Public login route.
 *
 * Middleware redirects already-authenticated users to their role landing path
 * before this page renders.
 */
import { AuthPageShell } from "@/components/modules/auth/auth-page-shell";
import { LoginForm } from "@/components/modules/auth/login-form";

export default function LoginPage() {
  return (
    <AuthPageShell
      eyebrow="Secure session"
      summary="Use your verified account credentials. If 2FA is enabled, the next step will ask for your authenticator code."
      title="Log in to continue marketplace work."
    >
      <LoginForm />
    </AuthPageShell>
  );
}
