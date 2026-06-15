/**
 * Authenticated admin route-group layout.
 */
import type { ReactNode } from "react";

import { AdminWorkspaceShell } from "@/components/modules/admin/admin-workspace-shell";

type AdminLayoutProps = {
  children: ReactNode;
};

/**
 * Render the admin workspace inside the shared authenticated shell.
 *
 * @param props - Nested route content.
 */
export default function AdminLayout({ children }: AdminLayoutProps) {
  return <AdminWorkspaceShell>{children}</AdminWorkspaceShell>;
}
