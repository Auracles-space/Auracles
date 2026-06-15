/**
 * Authenticated Projects route-group layout.
 */
import type { ReactNode } from "react";

type ProjectsLayoutProps = {
  children: ReactNode;
};

/**
 * Render project routes inside the shared authenticated shell.
 *
 * @param props - Nested Project route content.
 */
export default function ProjectsLayout({ children }: ProjectsLayoutProps) {
  return children;
}
