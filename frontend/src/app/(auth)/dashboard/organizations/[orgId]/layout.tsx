import { ReactNode } from "react";
import { OrganizationShell } from "@/components/modules/organizations/organization-shell";

export default async function OrganizationLayout({
  children,
  params,
}: {
  children: ReactNode;
  params: Promise<{ orgId: string }>;
}) {
  const { orgId } = await params;
  return <OrganizationShell orgId={orgId}>{children}</OrganizationShell>;
}
