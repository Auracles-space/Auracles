"use client";

/**
 * Authenticated account menu.
 *
 * Hydrates the current user from the existing refresh-cookie session, surfaces
 * active roles and identity details, and provides the live sign-out control
 * used by the authenticated shell.
 */
import Link from "next/link";
import { useEffect, useMemo, useState, useRef } from "react";

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
  const [isOpen, setIsOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

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

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, []);

  useEffect(() => {
    function handleAvatarUpdated(e: Event) {
      const customEvent = e as CustomEvent<string>;
      setCurrentUser((prev) => (prev ? { ...prev, avatar_url: customEvent.detail } : prev));
    }
    window.addEventListener("auracles-avatar-updated", handleAvatarUpdated);
    return () => {
      window.removeEventListener("auracles-avatar-updated", handleAvatarUpdated);
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
    <div className="relative w-full" ref={menuRef}>
      <button
        onClick={() => setIsOpen(!isOpen)}
        type="button"
        className="flex w-full cursor-pointer items-center gap-3 rounded-xl border border-transparent p-2 text-left outline-none transition-all hover:border-border-default hover:bg-black/5 focus-visible:ring-2 focus-visible:ring-accent dark:hover:bg-white/5"
      >
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-border-default bg-surface-3 text-sm font-semibold text-foreground overflow-hidden">
          {currentUser?.avatar_url ? (
            /* eslint-disable-next-line @next/next/no-img-element */
            <img src={currentUser.avatar_url} alt={displayName} className="h-full w-full object-cover" />
          ) : (
            avatarFallback
          )}
        </div>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium text-foreground">{displayName}</p>
          <p className="truncate text-xs text-foreground-muted">{email}</p>
        </div>
        <svg
          className={`h-4 w-4 shrink-0 text-foreground-muted transition-transform duration-200 ${
            isOpen ? "rotate-180" : ""
          }`}
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
      </button>

      {isOpen && (
        <div className="absolute bottom-full left-0 mb-3 w-full space-y-3 rounded-2xl border border-border-default bg-surface-1 p-4 shadow-bento z-50">
          {/* User Details & View Profile */}
          <div className="space-y-3">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-border-default bg-surface-3 text-sm font-semibold text-foreground overflow-hidden">
                {currentUser?.avatar_url ? (
                  /* eslint-disable-next-line @next/next/no-img-element */
                  <img src={currentUser.avatar_url} alt={displayName} className="h-full w-full object-cover" />
                ) : (
                  avatarFallback
                )}
              </div>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-semibold text-foreground leading-tight">{displayName}</p>
                <p className="truncate text-xs text-foreground-muted mt-0.5">{email}</p>
              </div>
            </div>
            <Link
              className="flex h-9 items-center justify-center rounded-xl border border-border-default bg-surface-2 px-3 text-xs font-semibold text-foreground transition-all hover:bg-surface-3 active:scale-[0.98] w-full"
              href="/profile/me"
              onClick={() => setIsOpen(false)}
            >
              View Profile
            </Link>
          </div>

          <div className="h-px bg-border-default" />

          {/* Settings & Theme */}
          <div className="space-y-2">
            <Link
              className="flex h-9 items-center rounded-xl px-3 text-xs font-medium text-foreground-muted hover:bg-surface-2 hover:text-foreground transition-colors"
              href="/settings/identity"
              onClick={() => setIsOpen(false)}
            >
              Settings & Preferences
            </Link>
            <div className="flex items-center justify-between rounded-xl bg-surface-2 px-3 py-1.5 border border-border-default">
              <span className="text-xs font-medium text-foreground-muted">Theme</span>
              <ThemeToggle />
            </div>
          </div>

          <div className="h-px bg-border-default" />

          {/* Active Roles */}
          <div className="space-y-1">
            <p className="text-[10px] font-bold uppercase tracking-wider text-foreground-subtle">
              Active Roles
            </p>
            <div className="flex flex-wrap gap-1.5">
              {roleLabels.map((label) => (
                <span
                  className="rounded border border-border-default bg-surface-2 px-1.5 py-0.5 text-[10px] font-medium text-foreground-muted"
                  key={label}
                >
                  {label}
                </span>
              ))}
            </div>
          </div>

          <div className="h-px bg-border-default" />

          {/* Sign Out Action */}
          <button
            className="flex h-9 w-full items-center justify-center rounded-xl text-xs font-semibold text-foreground-muted transition hover:bg-error/5 hover:text-error disabled:cursor-not-allowed disabled:opacity-60"
            disabled={signingOut}
            onClick={() => void handleSignOut()}
            type="button"
          >
            {signingOut ? "Signing out..." : "Sign Out"}
          </button>
        </div>
      )}
    </div>
  );
}
