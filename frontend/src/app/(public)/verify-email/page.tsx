/**
 * Email verification route.
 *
 * Accepts `?token=` from verification emails while still allowing manual
 * token entry for local development and tests.
 */
import { Suspense } from "react";

import { AuthPageShell } from "@/components/modules/auth/auth-page-shell";
import { VerifyEmailForm } from "@/components/modules/auth/verify-email-form";

type VerifyEmailPageProps = {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
};

function firstParam(value: string | string[] | undefined): string {
  return Array.isArray(value) ? value[0] ?? "" : value ?? "";
}

export default async function VerifyEmailPage({
  searchParams,
}: VerifyEmailPageProps) {
  const params = (await searchParams) ?? {};

  return (
    <AuthPageShell
      eyebrow="Email verification"
      summary="Email confirmation protects marketplace provenance and keeps account recovery tied to a verified address."
      title="Confirm ownership of your email address."
    >
      <Suspense fallback={null}>
        <VerifyEmailForm
          initialToken={firstParam(params.token)}
          initialEmail={firstParam(params.email)}
        />
      </Suspense>
    </AuthPageShell>
  );
}
