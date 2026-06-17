/**
 * Shared layout for onboarding and challenge route groups.
 *
 * Renders pages directly without the authenticated dashboard shell.
 */
import type { ReactNode } from "react";

type OnboardingLayoutProps = {
  children: ReactNode;
};

export default function OnboardingLayout({ children }: OnboardingLayoutProps) {
  return children;
}
