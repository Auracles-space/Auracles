import { InvitationAccept } from "@/components/modules/organizations/invitation-accept";

export default async function OrgInvitationPage({
  params,
}: {
  params: Promise<{ token: string }>;
}) {
  const { token } = await params;
  return <InvitationAccept token={token} />;
}
