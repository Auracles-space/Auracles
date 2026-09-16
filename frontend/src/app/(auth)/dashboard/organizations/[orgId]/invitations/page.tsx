/**
 * Old Invitations tab URL, kept so existing links still land: invitations now
 * live under the Members tab.
 */
import { redirect } from "next/navigation";

export default async function OrganizationInvitationsRedirect({
  params,
}: {
  params: Promise<{ orgId: string }>;
}) {
  const { orgId } = await params;
  redirect(`/dashboard/organizations/${orgId}/members/invitations`);
}
