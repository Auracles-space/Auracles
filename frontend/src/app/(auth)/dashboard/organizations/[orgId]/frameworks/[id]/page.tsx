"use client";

/**
 * Organization Framework editor route.
 *
 * Resolves route parameters and delegates to the extracted editor view so this
 * page module exports only its default route component.
 */
import { use } from "react";

import { OrgFrameworkEditor } from "@/components/modules/frameworks/org-framework-editor";

type OrgFrameworkEditorPageProps = {
  params: Promise<{ id: string; orgId: string }>;
};

/** Resolve route parameters and render the organization-scoped editor. */
export default function OrgFrameworkEditorPage({
  params,
}: OrgFrameworkEditorPageProps) {
  const { id, orgId } = use(params);
  return <OrgFrameworkEditor id={id} orgId={orgId} />;
}
