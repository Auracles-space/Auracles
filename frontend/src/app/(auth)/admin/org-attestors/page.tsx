/**
 * Legacy admin route. The attestor pipeline now lives at `/admin/attestors`.
 */
import { redirect } from "next/navigation";

/**
 * Redirect the old org-attestor review route to the attestor console.
 */
export default function AdminOrgAttestorsPage() {
  redirect("/admin/attestors?tab=applications");
}
