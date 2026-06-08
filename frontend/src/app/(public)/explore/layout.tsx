import type { ReactNode } from "react";
import { cookies } from "next/headers";

import { PublicMarketplaceShell } from "@/components/modules/layout/public-marketplace-shell";
import { AuthenticatedAppShell } from "@/components/modules/layout/authenticated-app-shell";

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
  const cookieStore = await cookies();
  const isAuthenticated = !!cookieStore.get("session_hint")?.value;

  if (isAuthenticated) {
    return <AuthenticatedAppShell>{children}</AuthenticatedAppShell>;
  }

  return <PublicMarketplaceShell>{children}</PublicMarketplaceShell>;
}
