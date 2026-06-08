/**
 * Public marketplace route-group layout.
 */
import type { ReactNode } from "react";

import { PublicMarketplaceShell } from "@/components/modules/layout/public-marketplace-shell";

type ExploreLayoutProps = {
  children: ReactNode;
};

/**
 * Wrap Explore routes in shared public product navigation.
 *
 * @param props - Nested Explore route content.
 */
export default function ExploreLayout({ children }: ExploreLayoutProps) {
  return <PublicMarketplaceShell>{children}</PublicMarketplaceShell>;
}
