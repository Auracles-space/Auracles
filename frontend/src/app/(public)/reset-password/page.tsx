/**
 * Password reset completion route.
 *
 * Accepts `?token=` from password reset emails and sends the new password to
 * the generated reset endpoint.
 */
import { AuthPageShell } from "@/components/modules/auth/auth-page-shell";
import { ResetPasswordForm } from "@/components/modules/auth/reset-password-form";

type ResetPasswordPageProps = {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
};

function firstParam(value: string | string[] | undefined): string {
  return Array.isArray(value) ? value[0] ?? "" : value ?? "";
}

export default async function ResetPasswordPage({
  searchParams,
}: ResetPasswordPageProps) {
  const params = (await searchParams) ?? {};

  return (
    <AuthPageShell
      eyebrow="Password reset"
      summary="Set a new password with the one-time token sent to your verified email address."
      title="Replace your password and revoke old sessions."
    >
      <ResetPasswordForm initialToken={firstParam(params.token)} />
    </AuthPageShell>
  );
}
