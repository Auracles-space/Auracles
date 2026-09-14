/**
 * Authenticated admin organization detail route.
 *
 * Maps to: organizations end-to-end design, Decision 1 and Slice D.
 */
import { Suspense } from "react";

import { AdminOrgDetail } from "@/components/modules/admin/org-detail/admin-org-detail";

export const metadata = {
  title: "Organization - Admin",
};

type AdminOrganizationDetailPageProps = {
  params: Promise<{ orgId: string }>;
};

/**
 * Render the detail page for one organization. Suspense satisfies
 * `useSearchParams` (the active tab) during rendering.
 *
 * @param props - Route params carrying the organization id.
 */
export default async function AdminOrganizationDetailPage({ params }: AdminOrganizationDetailPageProps) {
  const { orgId } = await params;
  return (
    <Suspense fallback={null}>
      <AdminOrgDetail orgId={orgId} />
    </Suspense>
  );
}
