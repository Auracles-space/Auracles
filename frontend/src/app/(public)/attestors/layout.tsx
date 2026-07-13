import type { ReactNode } from "react";

import { PublicMarketplaceShell } from "@/components/modules/layout/public-marketplace-shell";

type AttestorsLayoutProps = {
  children: ReactNode;
};

/**
 * Wrap Attestors routes in shared public product navigation.
 *
 * @param props - Nested Attestors route content.
 */
export default function AttestorsLayout({ children }: AttestorsLayoutProps) {
  return <PublicMarketplaceShell>{children}</PublicMarketplaceShell>;
}
