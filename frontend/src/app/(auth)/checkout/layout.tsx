/**
 * Authenticated checkout route-group layout.
 */
import type { ReactNode } from "react";

type CheckoutLayoutProps = {
  children: ReactNode;
};

/**
 * Render checkout routes inside the shared authenticated shell.
 *
 * @param props - Nested checkout content.
 */
export default function CheckoutLayout({ children }: CheckoutLayoutProps) {
  return children;
}
