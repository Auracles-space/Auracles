import { redirect } from "next/navigation";

export default async function OperatorRedirectPage({
  params,
}: {
  params: Promise<{ orgId: string }>;
}) {
  const { orgId } = await params;
  redirect(`/dashboard/organizations/${orgId}/operator/library`);
}
