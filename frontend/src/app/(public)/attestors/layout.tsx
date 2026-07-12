import type { ReactNode } from "react";

import { PublicMarketplaceShell } from "@/components/modules/layout/public-marketplace-shell";
import { AuthenticatedAppShell } from "@/components/modules/layout/authenticated-app-shell";
import { getVerifiedSessionHintFromCookies } from "@/lib/auth/server-session";

type AttestorsLayoutProps = {
  children: ReactNode;
};

/**
 * Wrap Attestors routes in shared public product navigation, or authenticated shell
 * if the user is logged in.
 *
 * @param props - Nested Attestors route content.
 */
export default async function AttestorsLayout({ children }: AttestorsLayoutProps) {
  const hint = await getVerifiedSessionHintFromCookies();

  if (hint) {
    return <AuthenticatedAppShell roles={hint.roles}>{children}</AuthenticatedAppShell>;
  }

  return <PublicMarketplaceShell>{children}</PublicMarketplaceShell>;
}
