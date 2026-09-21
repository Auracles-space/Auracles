"use client";

/**
 * Admin workspace shell.
 *
 * Provides focused local navigation for `/admin/*` routes while preserving the
 * shared authenticated product chrome outside the admin workspace.
 */
import { HamburgerMenuIcon } from "@radix-ui/react-icons";
import { usePathname } from "next/navigation";
import { useCallback, useEffect, useState, type ReactNode } from "react";

import {
  configureBrowserClient,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import { loadAdminReviewCounts } from "@/components/modules/admin/admin-review-counts";
import {
  NEEDS_ADMIN_CHANGED_EVENT,
  ORG_VERIFICATION_CHANGED_EVENT,
} from "@/components/modules/admin/admin-events";
import { useRefetchOnFocus } from "@/lib/hooks/use-refetch-on-focus";

import {
  AdminNavDrawer,
  AdminNavLinks,
  AdminWorkspaceIntro,
  currentAdminPageLabel,
} from "./admin-workspace-nav";

type AdminWorkspaceShellProps = {
  children: ReactNode;
};


/**
 * Render the local admin navigation and nested admin page content.
 *
 * @param props - Nested admin route content.
 */
export function AdminWorkspaceShell({ children }: AdminWorkspaceShellProps) {
  const pathname = usePathname() ?? "";
  const [badgeCounts, setBadgeCounts] = useState<Record<string, number>>({});
  const [menuOpen, setMenuOpen] = useState(false);
  const closeMenu = useCallback(() => setMenuOpen(false), []);

  const refreshCounts = useCallback(() => {
    // Counts are badges, not pages: a failure leaves the badge at zero rather
    // than rejecting, because this shell wraps every admin route and an
    // uncaught rejection would land on a screen unrelated to the failed queue.
    configureBrowserClient();
    void loadAdminReviewCounts(getAccessTokenHeaders()).then(setBadgeCounts);
  }, []);

  useEffect(() => {
    refreshCounts();
  }, [refreshCounts]);
  // Badges otherwise load once, so work submitted while an admin page is open
  // (an attestor application, a dispute) showed no count until a reload.
  useRefetchOnFocus(refreshCounts);

  useEffect(() => {
    const onChanged = () => refreshCounts();
    const onOrgVerificationChanged = () => refreshCounts();
    window.addEventListener(NEEDS_ADMIN_CHANGED_EVENT, onChanged);
    window.addEventListener(ORG_VERIFICATION_CHANGED_EVENT, onOrgVerificationChanged);
    return () => {
      window.removeEventListener(NEEDS_ADMIN_CHANGED_EVENT, onChanged);
      window.removeEventListener(ORG_VERIFICATION_CHANGED_EVENT, onOrgVerificationChanged);
    };
  }, [refreshCounts]);

  const attentionTotal = Object.values(badgeCounts).reduce((sum, count) => sum + count, 0);
  const currentLabel = currentAdminPageLabel(pathname);

  return (
    <section className="px-4 py-6 text-foreground md:px-8 md:py-8">
      <div className="mx-auto grid max-w-[1280px] gap-6 xl:grid-cols-[240px_minmax(0,1fr)]">
        <div className="flex items-center justify-between gap-3 rounded-2xl border border-border-default bg-surface-1 px-4 py-3 shadow-sm xl:hidden">
          <div className="min-w-0">
            <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
              Admin workspace
            </p>
            <p
              className="truncate font-heading text-lg font-bold text-foreground"
              data-testid="admin-current-page"
            >
              {currentLabel ?? "Operations"}
            </p>
          </div>
          <button
            aria-controls="admin-nav-drawer"
            aria-expanded={menuOpen}
            aria-label={
              attentionTotal > 0
                ? `Admin menu, ${attentionTotal} item${attentionTotal === 1 ? "" : "s"} need${attentionTotal === 1 ? "s" : ""} attention`
                : "Admin menu"
            }
            className="relative inline-flex min-h-12 shrink-0 items-center gap-2 rounded-xl border border-border-default bg-surface-1 px-4 text-sm font-semibold text-foreground hover:bg-surface-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
            onClick={() => setMenuOpen(true)}
            type="button"
          >
            <HamburgerMenuIcon aria-hidden="true" className="h-5 w-5" />
            Menu
            {attentionTotal > 0 ? (
              <span
                aria-hidden="true"
                className="inline-flex min-w-5 items-center justify-center rounded-badge bg-accent px-1.5 text-xs font-bold text-background"
              >
                {attentionTotal}
              </span>
            ) : null}
          </button>
        </div>

        <aside className="hidden content-start gap-4 xl:grid">
          <AdminWorkspaceIntro />
          <nav
            aria-label="Admin navigation"
            className="rounded-2xl border border-border-default bg-surface-1 p-4 shadow-sm"
          >
            <AdminNavLinks badgeCounts={badgeCounts} pathname={pathname} />
          </nav>
        </aside>

        <div className="min-w-0">{children}</div>
      </div>

      {/* Outside the layout grid: even closed, a grid child would take the
          page's column on wide screens and push the page under the sidebar. */}
      <AdminNavDrawer onClose={closeMenu} open={menuOpen}>
        <AdminWorkspaceIntro />
        <AdminNavLinks badgeCounts={badgeCounts} onNavigate={closeMenu} pathname={pathname} />
      </AdminNavDrawer>
    </section>
  );
}
