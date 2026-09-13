import { AdminOrgVerificationQueue } from "@/components/modules/admin/admin-org-verification-queue";
import { AdminOrganizationsList } from "@/components/modules/organizations/admin-organizations-list";

export const metadata = {
  title: "Organizations - Admin",
};

/**
 * Admin organizations page.
 *
 * Business verification leads: an organization waiting here cannot activate any
 * capability, so clearing the queue is what unblocks org onboarding.
 */
export default function AdminOrganizationsPage() {
  return (
    <div className="grid gap-8">
      <div className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
        <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">Trust</p>
        <h1 className="mt-2 font-heading text-3xl font-bold text-foreground">Organizations</h1>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-foreground-muted">
          Verify businesses before they can act, then search, suspend, or reinstate any
          organization. Verdicts, suspensions, and reinstatements require a step-up window.
        </p>
      </div>
      <AdminOrgVerificationQueue />
      <AdminOrganizationsList />
    </div>
  );
}
