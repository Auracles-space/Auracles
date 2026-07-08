/**
 * Authenticated admin Org Attestor review route.
 */
import { Metadata } from "next";
import { AdminOrgAttestorReviewPanel } from "@/components/modules/admin/admin-org-attestor-review-panel";

export const metadata: Metadata = {
  title: "Admin - Org Attestors",
};

export default function AdminOrgAttestorsPage() {
  return (
    <div className="max-w-5xl mx-auto space-y-6">
      <AdminOrgAttestorReviewPanel />
    </div>
  );
}
