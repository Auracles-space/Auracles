"use client";

/**
 * Authenticated settings route-group layout.
 */
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { SettingsWorkspaceShell } from "@/components/modules/settings/settings-workspace-shell";

type SettingsLayoutProps = {
  children: ReactNode;
};

/**
 * Render settings routes inside the shared authenticated shell.
 *
 * @param props - Nested settings content.
 */
export default function SettingsLayout({ children }: SettingsLayoutProps) {
  const pathname = usePathname() ?? "";

  // Bypasses the navigation shell for financial and search alert pages.
  const isExcluded =
    pathname.startsWith("/settings/payment-methods") ||
    pathname.startsWith("/settings/payout-accounts") ||
    pathname.startsWith("/settings/saved-searches");

  if (isExcluded) {
    return children;
  }

  return <SettingsWorkspaceShell>{children}</SettingsWorkspaceShell>;
}

