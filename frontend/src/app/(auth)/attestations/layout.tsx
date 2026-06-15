/**
 * Authenticated Attestation route-group layout.
 */
import type { ReactNode } from "react";

type AttestationLayoutProps = {
  children: ReactNode;
};

/**
 * Render attestation routes inside the shared authenticated shell.
 *
 * @param props - Nested route content.
 */
export default function AttestationLayout({ children }: AttestationLayoutProps) {
  return children;
}
