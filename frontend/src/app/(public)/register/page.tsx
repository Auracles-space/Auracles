/**
 * Public registration route.
 *
 * Hosts the Slice 10 registration form in the shared auth shell.
 */
import { AuthPageShell } from "@/components/modules/auth/auth-page-shell";
import { RegisterForm } from "@/components/modules/auth/register-form";

export default function RegisterPage() {
  return (
    <AuthPageShell
      eyebrow="Account access"
      summary="Create an account, verify your email, and choose the marketplace role that matches your work."
      title="Start with a verified professional account."
    >
      <RegisterForm />
    </AuthPageShell>
  );
}
