/**
 * Authenticated settings route-group layout.
 */
import type { ReactNode } from "react";

import { AuthenticatedAppShell } from "@/components/modules/layout/authenticated-app-shell";

type SettingsLayoutProps = {
  children: ReactNode;
};

/**
 * Wrap settings routes in persistent app navigation.
 *
 * @param props - Nested settings content.
 */
export default function SettingsLayout({ children }: SettingsLayoutProps) {
  return <AuthenticatedAppShell>{children}</AuthenticatedAppShell>;
}
