/**
 * Authenticated dashboard route-group layout.
 */
import type { ReactNode } from "react";

import { AuthenticatedAppShell } from "@/components/modules/layout/authenticated-app-shell";

type DashboardLayoutProps = {
  children: ReactNode;
};

/**
 * Wrap Contributor dashboard routes in persistent app navigation.
 *
 * @param props - Nested dashboard content.
 */
export default function DashboardLayout({ children }: DashboardLayoutProps) {
  return <AuthenticatedAppShell>{children}</AuthenticatedAppShell>;
}
