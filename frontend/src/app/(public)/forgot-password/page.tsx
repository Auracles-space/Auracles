/**
 * Password reset request route.
 *
 * Uses backend no-enumeration semantics so the page never confirms whether an
 * email address exists.
 */
import { AuthPageShell } from "@/components/modules/auth/auth-page-shell";
import { ForgotPasswordForm } from "@/components/modules/auth/forgot-password-form";

export default function ForgotPasswordPage() {
  return (
    <AuthPageShell
      eyebrow="Account recovery"
      summary="Request a reset link for the email on your account. The link expires quickly and revokes active sessions after use."
      title="Recover access without exposing account status."
    >
      <ForgotPasswordForm />
    </AuthPageShell>
  );
}
