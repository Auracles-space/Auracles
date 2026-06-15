/**
 * Authenticated dashboard route-group layout.
 */
import type { ReactNode } from "react";

type DashboardLayoutProps = {
  children: ReactNode;
};

/**
 * Render contributor dashboard routes inside the shared authenticated shell.
 *
 * @param props - Nested dashboard content.
 */
export default function DashboardLayout({ children }: DashboardLayoutProps) {
  return children;
}
