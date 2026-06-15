import type { ReactNode } from "react";

import { PublicMarketplaceShell } from "@/components/modules/layout/public-marketplace-shell";
import { AuthenticatedAppShell } from "@/components/modules/layout/authenticated-app-shell";
import { getVerifiedSessionHintFromCookies } from "@/lib/auth/server-session";

type ExploreLayoutProps = {
  children: ReactNode;
};

/**
 * Wrap Explore routes in shared public product navigation, or authenticated shell
 * if the user is logged in.
 *
 * @param props - Nested Explore route content.
 */
export default async function ExploreLayout({ children }: ExploreLayoutProps) {
  const hint = await getVerifiedSessionHintFromCookies();

  if (hint) {
    return <AuthenticatedAppShell roles={hint.roles}>{children}</AuthenticatedAppShell>;
  }

  return <PublicMarketplaceShell>{children}</PublicMarketplaceShell>;
}
