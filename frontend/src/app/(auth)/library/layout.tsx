/**
 * Authenticated library route-group layout.
 */
import type { ReactNode } from "react";

type LibraryLayoutProps = {
  children: ReactNode;
};

/**
 * Render operator library routes inside the shared authenticated shell.
 *
 * @param props - Nested library content.
 */
export default function LibraryLayout({ children }: LibraryLayoutProps) {
  return children;
}
