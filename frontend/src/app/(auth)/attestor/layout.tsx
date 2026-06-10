/**
 * Authenticated Attestor route-group layout.
 */
import type { ReactNode } from "react";

import { AuthenticatedAppShell } from "@/components/modules/layout/authenticated-app-shell";

type AttestorLayoutProps = {
  children: ReactNode;
};

/**
 * Wrap Attestor routes in persistent authenticated navigation.
 *
 * @param props - Nested route content.
 */
export default function AttestorLayout({ children }: AttestorLayoutProps) {
  return <AuthenticatedAppShell>{children}</AuthenticatedAppShell>;
}
