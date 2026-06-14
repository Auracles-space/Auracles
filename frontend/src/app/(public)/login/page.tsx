/**
 * Public login route.
 *
 * Middleware redirects already-authenticated users to their role landing path
 * before this page renders.
 */
import { AuthPageShell } from "@/components/modules/auth/auth-page-shell";
import { LoginForm } from "@/components/modules/auth/login-form";

type LoginPageProps = {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
};

function firstParam(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

export default async function LoginPage({ searchParams }: LoginPageProps) {
  const params = (await searchParams) ?? {};

  return (
    <AuthPageShell
      eyebrow="Secure session"
      summary="Use your verified account credentials. If 2FA is enabled, the next step will ask for your authenticator code."
      title="Log in to continue marketplace work."
    >
      <LoginForm next={firstParam(params.next)} />
    </AuthPageShell>
  );
}
