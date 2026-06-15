/**
 * Authenticated Attestor route-group layout.
 */
import type { ReactNode } from "react";

type AttestorLayoutProps = {
  children: ReactNode;
};

/**
 * Render attestor routes inside the shared authenticated shell.
 *
 * @param props - Nested route content.
 */
export default function AttestorLayout({ children }: AttestorLayoutProps) {
  return children;
}
