"use client";

import { useRouter } from "next/navigation";
import type { ReactNode } from "react";

type BackButtonProps = {
  /** The fallback destination URL if there is no browser history to go back to. */
  fallbackHref: string;
  /** Inner content of the link/button. */
  children: ReactNode;
  /** Optional tailwind styles. */
  className?: string;
};

/**
 * A client-side button that performs a smart history back navigation.
 *
 * Falls back to a standard anchor tag href if no history exists (e.g. direct visits),
 * preventing users from getting trapped or losing their query parameters/filters.
 */
export function BackButton({ fallbackHref, children, className }: BackButtonProps) {
  const router = useRouter();

  const handleBack = (e: React.MouseEvent<HTMLAnchorElement>) => {
    // If there is browser history from a prior page on this domain, use it to preserve filters/state
    if (typeof window !== "undefined" && window.history.length > 1) {
      e.preventDefault();
      router.back();
    }
  };

  return (
    <a
      href={fallbackHref}
      onClick={handleBack}
      className={className}
    >
      {children}
    </a>
  );
}
