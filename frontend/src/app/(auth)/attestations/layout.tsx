/**
 * Authenticated Attestation route-group layout.
 */
import type { ReactNode } from "react";

import { AuthenticatedAppShell } from "@/components/modules/layout/authenticated-app-shell";

type AttestationLayoutProps = {
  children: ReactNode;
};

/**
 * Wrap Attestation routes in persistent authenticated navigation.
 *
 * @param props - Nested route content.
 */
export default function AttestationLayout({ children }: AttestationLayoutProps) {
  return <AuthenticatedAppShell>{children}</AuthenticatedAppShell>;
}
