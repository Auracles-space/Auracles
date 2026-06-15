/**
 * Shared authenticated route-group layout.
 *
 * Verifies the signed session hint on the server and feeds the role-filtered
 * authenticated shell used across dashboard, library, projects, settings, and
 * admin workspaces.
 */
import type { ReactNode } from "react";
import { headers } from "next/headers";
import { redirect } from "next/navigation";

import { AuthenticatedAppShell } from "@/components/modules/layout/authenticated-app-shell";
import { getVerifiedSessionHintFromCookies } from "@/lib/auth/server-session";

type AuthLayoutProps = {
  children: ReactNode;
};

const preSessionPaths = new Set(["/2fa-challenge", "/settings/onboarding"]);

/**
 * Render the shared authenticated shell for all protected route groups.
 *
 * @param props - Nested authenticated route content.
 */
export default async function AuthLayout({ children }: AuthLayoutProps) {
  const requestHeaders = await headers();
  const pathname = requestHeaders.get("x-auracles-pathname");
  if (pathname && preSessionPaths.has(pathname)) {
    return children;
  }

  const hint = await getVerifiedSessionHintFromCookies();

  if (!hint) {
    redirect("/login");
  }

  return <AuthenticatedAppShell roles={hint.roles}>{children}</AuthenticatedAppShell>;
}
