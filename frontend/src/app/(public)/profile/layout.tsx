import type { ReactNode } from "react";

import { PublicMarketplaceShell } from "@/components/modules/layout/public-marketplace-shell";
import { AuthenticatedAppShell } from "@/components/modules/layout/authenticated-app-shell";
import { getVerifiedSessionHintFromCookies } from "@/lib/auth/server-session";

type ProfileLayoutProps = {
  children: ReactNode;
};

/**
 * Wrap Profile routes in shared public product navigation, or authenticated shell
 * if the user is logged in.
 *
 * @param props - Nested Profile route content.
 */
export default async function ProfileLayout({ children }: ProfileLayoutProps) {
  const hint = await getVerifiedSessionHintFromCookies();

  if (hint) {
    return <AuthenticatedAppShell roles={hint.roles}>{children}</AuthenticatedAppShell>;
  }

  return <PublicMarketplaceShell>{children}</PublicMarketplaceShell>;
}
