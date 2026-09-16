/**
 * Old Offers tab URL, kept so links in sent emails and notifications still
 * land: offers now live under the Attestor tab.
 */
import { redirect } from "next/navigation";

export default async function OrganizationOffersRedirect({
  params,
}: {
  params: Promise<{ orgId: string }>;
}) {
  const { orgId } = await params;
  redirect(`/dashboard/organizations/${orgId}/attestor/offers`);
}
