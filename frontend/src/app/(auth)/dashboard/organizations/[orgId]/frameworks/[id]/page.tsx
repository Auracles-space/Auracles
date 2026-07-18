"use client";

/**
 * Organization Framework editor route.
 *
 * Uses the membership already loaded by OrganizationShell to gate commercial
 * and marketplace lifecycle controls to organization admins and owners.
 */
import { use } from "react";

import { FrameworkEditor } from "@/components/modules/frameworks/framework-editor";
import { useOrganization } from "@/components/modules/organizations/organization-context";

type OrgFrameworkEditorPageProps = {
  params: Promise<{ id: string; orgId: string }>;
};

type OrgFrameworkEditorProps = {
  id: string;
  orgId: string;
};

/** Render the editor after route parameters have resolved. */
export function OrgFrameworkEditor({ id, orgId }: OrgFrameworkEditorProps) {
  const { role } = useOrganization();
  const canManageLiveState = role === "owner" || role === "admin";

  return (
    <FrameworkEditor
      basePath={`/dashboard/organizations/${orgId}/frameworks`}
      canManageLiveState={canManageLiveState}
      frameworkId={id}
      seller={{ kind: "org", orgId }}
    />
  );
}

/** Resolve route parameters and render the organization-scoped editor. */
export default function OrgFrameworkEditorPage({
  params,
}: OrgFrameworkEditorPageProps) {
  const { id, orgId } = use(params);
  return <OrgFrameworkEditor id={id} orgId={orgId} />;
}
