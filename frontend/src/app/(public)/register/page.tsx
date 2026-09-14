/**
 * Public registration route.
 *
 * Hosts the registration form in the shared auth shell. The form reads
 * `?next=` on the client, so it sits in a Suspense boundary as Next.js
 * requires for `useSearchParams` on a statically rendered page.
 */
import { Suspense } from "react";

import { AuthPageShell } from "@/components/modules/auth/auth-page-shell";
import { RegisterForm } from "@/components/modules/auth/register-form";

export default function RegisterPage() {
  return (
    <AuthPageShell
      eyebrow="Account access"
      summary="Create an account, verify your email, and choose the marketplace role that matches your work."
      title="Start with a verified professional account."
    >
      <Suspense fallback={null}>
        <RegisterForm />
      </Suspense>
    </AuthPageShell>
  );
}
