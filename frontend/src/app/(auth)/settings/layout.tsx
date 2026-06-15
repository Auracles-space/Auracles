/**
 * Authenticated settings route-group layout.
 */
import type { ReactNode } from "react";

type SettingsLayoutProps = {
  children: ReactNode;
};

/**
 * Render settings routes inside the shared authenticated shell.
 *
 * @param props - Nested settings content.
 */
export default function SettingsLayout({ children }: SettingsLayoutProps) {
  return children;
}
