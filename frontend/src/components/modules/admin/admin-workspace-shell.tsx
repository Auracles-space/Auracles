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
import {
  adminListOrgsV1AdminOrgsGet,
  listAdminAttestationDisputes,
  listAdminAttestations,
  listAdminProjectDisputes,
  listOrgAttestorApplicationsForAdmin,
} from "@/lib/generated/sdk.gen";
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
  const [needsAdminCount, setNeedsAdminCount] = useState(0);
  const [attestorCount, setAttestorCount] = useState(0);
  const [disputeCount, setDisputeCount] = useState(0);
  const [pendingOrgCount, setPendingOrgCount] = useState(0);
  const [menuOpen, setMenuOpen] = useState(false);
  const closeMenu = useCallback(() => setMenuOpen(false), []);

  const refreshCounts = useCallback(() => {
    async function loadNeedsAdminCount() {
      configureBrowserClient();
      // The count is a badge, not the page. A failed request leaves it at zero
      // rather than rejecting: this shell wraps every admin route, so an
      // uncaught rejection here lands on screens unrelated to attestations.
      let result;
      try {
        result = await listAdminAttestations({
          headers: getAccessTokenHeaders(),
          query: { status: "needs_admin" },
        });
      } catch {
        return;
      }
      if (result.response.ok && result.data) {
        setNeedsAdminCount(result.data.attestations.length);
      }
    }
    async function loadTrustCounts() {
      configureBrowserClient();
      const headers = getAccessTokenHeaders();
      try {
        const [applications, attestationDisputes, projectDisputes] = await Promise.all([
          listOrgAttestorApplicationsForAdmin({ headers, query: { status: "submitted" } }),
          listAdminAttestationDisputes({ headers, query: { status: "active" } }),
          listAdminProjectDisputes({ headers }),
        ]);
        if (applications.response.ok && applications.data) {
          setAttestorCount(applications.data.applications.length);
        }
        const open =
          (attestationDisputes.response.ok && attestationDisputes.data
            ? attestationDisputes.data.disputes.length
            : 0) +
          (projectDisputes.response.ok && projectDisputes.data
            ? projectDisputes.data.disputes.filter((dispute: { status: string }) => dispute.status !== "resolved")
                .length
            : 0);
        setDisputeCount(open);
      } catch {
        return;
      }
    }
    async function loadPendingOrgCount() {
      configureBrowserClient();
      // One row is enough: the badge reads the total, and a failure leaves it
      // at zero for the same reason as the needs-admin count above.
      try {
        const result = await adminListOrgsV1AdminOrgsGet({
          headers: getAccessTokenHeaders(),
          query: { kyb_status: "pending", page: 1, page_size: 1 },
        });
        if (result.response.ok && result.data) {
          setPendingOrgCount(result.data.total);
        }
      } catch {
        return;
      }
    }
    void loadNeedsAdminCount();
    void loadTrustCounts();
    void loadPendingOrgCount();
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

  const badgeCounts: Record<string, number> = {
    "/admin/attestations": needsAdminCount,
    "/admin/attestors": attestorCount,
    "/admin/disputes": disputeCount,
    "/admin/organizations": pendingOrgCount,
  };

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

        <div id="admin-nav-drawer">
          <AdminNavDrawer onClose={closeMenu} open={menuOpen}>
            <AdminWorkspaceIntro />
            <AdminNavLinks
              badgeCounts={badgeCounts}
              onNavigate={closeMenu}
              pathname={pathname}
            />
          </AdminNavDrawer>
        </div>

        <div className="min-w-0">{children}</div>
      </div>
    </section>
  );
}
