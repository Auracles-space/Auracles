/**
 * Old Teams tab URL, kept so existing links still land: teams now live under
 * the Members tab.
 */
import { redirect } from "next/navigation";

export default async function OrganizationTeamsRedirect({
  params,
}: {
  params: Promise<{ orgId: string }>;
}) {
  const { orgId } = await params;
  redirect(`/dashboard/organizations/${orgId}/members/teams`);
}
