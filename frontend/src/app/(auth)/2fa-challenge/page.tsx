/**
 * Login 2FA challenge route.
 *
 * This route is part of the auth workflow but is not session-gated: the
 * backend deliberately withholds refresh/session cookies until the challenge
 * is completed successfully.
 */
import { AuthPageShell } from "@/components/modules/auth/auth-page-shell";
import { TotpChallengeForm } from "@/components/modules/auth/totp-challenge-form";

type TotpChallengePageProps = {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
};

function firstParam(value: string | string[] | undefined): string {
  return Array.isArray(value) ? value[0] ?? "" : value ?? "";
}

export default async function TotpChallengePage({
  searchParams,
}: TotpChallengePageProps) {
  const params = (await searchParams) ?? {};

  return (
    <AuthPageShell
      eyebrow="Two-factor login"
      summary="Complete this short challenge before the browser receives a refresh cookie and signed session hint."
      title="Confirm this login with your second factor."
    >
      <TotpChallengeForm challengeToken={firstParam(params.challenge)} />
    </AuthPageShell>
  );
}
