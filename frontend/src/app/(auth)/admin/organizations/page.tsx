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
      <AdminOrgVerificationQueue />
      <AdminOrganizationsList />
    </div>
  );
}
