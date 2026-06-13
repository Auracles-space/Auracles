/**
 * Authenticated admin route-group layout.
 */
import type { ReactNode } from "react";

import { AdminWorkspaceShell } from "@/components/modules/admin/admin-workspace-shell";
import { AuthenticatedAppShell } from "@/components/modules/layout/authenticated-app-shell";

type AdminLayoutProps = {
  children: ReactNode;
};

/**
 * Wrap admin routes in persistent authenticated navigation.
 *
 * @param props - Nested route content.
 */
export default function AdminLayout({ children }: AdminLayoutProps) {
  return (
    <AuthenticatedAppShell>
      <AdminWorkspaceShell>{children}</AdminWorkspaceShell>
    </AuthenticatedAppShell>
  );
}
