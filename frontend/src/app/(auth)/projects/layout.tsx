/**
 * Authenticated Projects route-group layout.
 */
import type { ReactNode } from "react";

import { AuthenticatedAppShell } from "@/components/modules/layout/authenticated-app-shell";

type ProjectsLayoutProps = {
  children: ReactNode;
};

/**
 * Wrap Project routes in persistent authenticated navigation.
 *
 * @param props - Nested Project route content.
 */
export default function ProjectsLayout({ children }: ProjectsLayoutProps) {
  return <AuthenticatedAppShell>{children}</AuthenticatedAppShell>;
}
