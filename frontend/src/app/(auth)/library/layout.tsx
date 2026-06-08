/**
 * Authenticated library route-group layout.
 */
import type { ReactNode } from "react";

import { AuthenticatedAppShell } from "@/components/modules/layout/authenticated-app-shell";

type LibraryLayoutProps = {
  children: ReactNode;
};

/**
 * Wrap Operator library routes in persistent app navigation.
 *
 * @param props - Nested library content.
 */
export default function LibraryLayout({ children }: LibraryLayoutProps) {
  return <AuthenticatedAppShell>{children}</AuthenticatedAppShell>;
}
