import type { ReactNode } from "react";
import { redirect } from "next/navigation";

import { AuthenticatedAppShell } from "@/components/modules/layout/authenticated-app-shell";
import { getVerifiedSessionHintFromCookies } from "@/lib/auth/server-session";

type AuthLayoutProps = {
  children: ReactNode;
};

/**
 * Render the shared authenticated shell for all protected route groups.
 *
 * @param props - Nested authenticated route content.
 */
export default async function AuthLayout({ children }: AuthLayoutProps) {
  const hint = await getVerifiedSessionHintFromCookies();

  if (!hint) {
    redirect("/login");
  }

  return <AuthenticatedAppShell roles={hint.roles}>{children}</AuthenticatedAppShell>;
}

