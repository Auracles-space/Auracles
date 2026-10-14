/**
 * Organization Project edit route.
 *
 * Keeps organization-operated edits inside the organization dashboard, reusing
 * the shared edit form with an explicit organization identity.
 */
import Link from "next/link";

import { ProjectEditForm } from "@/components/modules/projects/project-edit-form";

type OrgProjectEditPageProps = {
  params: Promise<{ id: string; orgId: string }>;
};

/**
 * Render the edit form for one organization-operated Project.
 *
 * @param props - Next route params.
 */
export default async function OrgProjectEditPage({
  params,
}: OrgProjectEditPageProps) {
  const { id, orgId } = await params;
  return (
    <main className="mx-auto grid max-w-4xl gap-8 px-4 py-10 text-foreground md:px-8">
      <div>
        <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
          Edit Project
        </p>
        <h1 className="mt-2 font-heading text-3xl font-bold">
          Update this Project
        </h1>
        <p className="mt-3 text-sm leading-6 text-foreground-muted">
          Changes apply while the Project is still open. Budget and
          deliverables close once a Contributor has submitted a Proposal
          against them.
        </p>
        <Link
          className="mt-3 inline-block text-sm font-semibold text-accent hover:underline"
          href={`/dashboard/organizations/${orgId}/projects/${id}`}
        >
          Back to the workspace
        </Link>
      </div>
      <section className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
        <ProjectEditForm mode={{ kind: "org", orgId }} projectId={id} />
      </section>
    </main>
  );
}
