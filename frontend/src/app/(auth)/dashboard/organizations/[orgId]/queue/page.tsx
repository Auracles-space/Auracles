/**
 * Old Queue tab URL, kept so existing links and bookmarks still land: the
 * review queue now lives under the Attestor tab.
 */
import { redirect } from "next/navigation";

export default async function OrganizationQueueRedirect({
  params,
}: {
  params: Promise<{ orgId: string }>;
}) {
  const { orgId } = await params;
  redirect(`/dashboard/organizations/${orgId}/attestor/queue`);
}
