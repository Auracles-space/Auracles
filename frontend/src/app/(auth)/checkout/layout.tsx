/**
 * Authenticated checkout route-group layout.
 */
import type { ReactNode } from "react";

import { AuthenticatedAppShell } from "@/components/modules/layout/authenticated-app-shell";

type CheckoutLayoutProps = {
  children: ReactNode;
};

/**
 * Wrap checkout routes in persistent authenticated navigation.
 *
 * @param props - Nested checkout content.
 */
export default function CheckoutLayout({ children }: CheckoutLayoutProps) {
  return <AuthenticatedAppShell>{children}</AuthenticatedAppShell>;
}
