"use client";

/**
 * Authenticated account menu.
 *
 * Hydrates the current user from the existing refresh-cookie session, surfaces
 * active roles and identity details, and provides the live sign-out control
 * used by the authenticated shell.
 */
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { ThemeToggle } from "@/components/ui/theme-toggle";
import {
  clearBrowserSessionHintCookie,
  loadCurrentUserSession,
} from "@/lib/auth/current-user-session";
import { configureBrowserClient, getAccessTokenHeaders } from "@/lib/auth/form-client";
import { clearAuthToken } from "@/lib/auth/token-store";
import { logoutV1AuthLogoutPost } from "@/lib/generated/sdk.gen";
import type { CurrentUserResponse } from "@/lib/generated/types.gen";

type AuthenticatedAccountMenuProps = {
  roles: string[];
};

/**
 * Convert backend role identifiers into concise menu labels.
 *
 * @param role - Raw role slug from auth state.
 */
function formatRoleLabel(role: string): string {
  switch (role) {
    case "admin":
      return "Admin";
    case "attestor":
      return "Attestor";
    case "contributor":
      return "Contributor";
    case "operator":
      return "Operator";
    default:
      return role;
  }
}

/**
 * Build fallback initials for the current account avatar tile.
 *
 * @param displayName - Current account display name.
 */
function initialsForDisplayName(displayName: string): string {
  return displayName
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("");
}

/**
 * Render the authenticated account menu and sign-out action.
 *
 * @param props - Active roles from the verified session hint.
 */
export function AuthenticatedAccountMenu({
  roles,
}: AuthenticatedAccountMenuProps) {
  const [currentUser, setCurrentUser] = useState<CurrentUserResponse | null>(null);
  const [signingOut, setSigningOut] = useState(false);

  useEffect(() => {
    let mounted = true;

    async function hydrateCurrentUser(): Promise<void> {
      const user = await loadCurrentUserSession();
      if (mounted) {
        setCurrentUser(user);
      }
    }

    void hydrateCurrentUser();
    return () => {
      mounted = false;
    };
  }, []);

  const roleLabels = useMemo(
    () => roles.map((role) => formatRoleLabel(role)),
    [roles],
  );
  const displayName = currentUser?.display_name ?? "Account";
  const email = currentUser?.email ?? "Authenticated user";
  const avatarFallback = initialsForDisplayName(displayName) || "AU";

  async function handleSignOut(): Promise<void> {
    setSigningOut(true);
    configureBrowserClient();
    await logoutV1AuthLogoutPost({
      headers: getAccessTokenHeaders(),
    }).catch(() => undefined);
    clearAuthToken();
    clearBrowserSessionHintCookie();
    window.location.assign("/login");
  }

  return (
    <details className="group relative w-full">
      <summary className="flex w-full cursor-pointer list-none items-center gap-3 rounded-xl border border-transparent p-2 text-left outline-none transition-all hover:border-border-default hover:bg-black/5 focus-visible:ring-2 focus-visible:ring-accent dark:hover:bg-white/5">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-border-default bg-surface-3 text-sm font-semibold text-foreground">
          {avatarFallback}
        </div>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium text-foreground">{displayName}</p>
          <p className="truncate text-xs text-foreground-muted">{email}</p>
        </div>
        <svg
          className="h-4 w-4 shrink-0 text-foreground-muted transition-transform group-open:rotate-180"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M19 9l-7 7-7-7"
          />
        </svg>
      </summary>

      <div className="mt-3 space-y-4 rounded-xl border border-border-default bg-surface-1 p-4 md:absolute md:bottom-full md:left-0 md:mb-3 md:mt-0 md:w-full">
        <div className="space-y-2">
          <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
            Active roles
          </p>
          <div className="flex flex-wrap gap-2">
            {roleLabels.map((label) => (
              <span
                className="rounded-md border border-border-default bg-surface-2 px-2 py-1 text-xs font-medium text-foreground"
                key={label}
              >
                {label}
              </span>
            ))}
          </div>
        </div>

        <div className="flex items-center justify-between gap-3 rounded-xl border border-border-default bg-surface-2 px-3 py-2">
          <div>
            <p className="text-sm font-medium text-foreground">Theme</p>
            <p className="text-xs text-foreground-muted">Switch light and dark mode</p>
          </div>
          <ThemeToggle />
        </div>

        <div className="flex flex-col gap-2">
          <Link
            className="flex min-h-11 items-center justify-center rounded-lg border border-border-default bg-surface-2 px-3 py-2 text-sm font-medium text-foreground transition hover:bg-surface-3"
            href="/settings/profile"
          >
            View profile
          </Link>
          <button
            className="flex min-h-11 items-center justify-center rounded-lg border border-error/30 bg-error/10 px-3 py-2 text-sm font-medium text-error transition hover:bg-error/15 disabled:cursor-not-allowed disabled:opacity-60"
            disabled={signingOut}
            onClick={() => void handleSignOut()}
            type="button"
          >
            {signingOut ? "Signing out..." : "Sign out"}
          </button>
        </div>
      </div>
    </details>
  );
}
