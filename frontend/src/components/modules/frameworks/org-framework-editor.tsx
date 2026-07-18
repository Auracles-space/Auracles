"use client";

/**
 * Organization Framework editor view.
 *
 * Extracted from the route file so the page module exports only its default
 * route component — Next.js rejects extra named exports from page files
 * (`next build`/`tsc` type error otherwise).
 */
import { FrameworkEditor } from "@/components/modules/frameworks/framework-editor";
import { useOrganization } from "@/components/modules/organizations/organization-context";

type OrgFrameworkEditorProps = {
  id: string;
  orgId: string;
};

/**
 * Render the org-scoped Framework editor, gating live-state controls by role.
 *
 * @param props - Resolved framework id and organization id from the route.
 */
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
