/**
 * Project edit route.
 *
 * Mirrors the posting page so an Operator correcting a Project meets the same
 * fields in the same order they filled them in.
 */
import Link from "next/link";

import { ProjectEditForm } from "@/components/modules/projects/project-edit-form";

type ProjectEditPageProps = {
  params: Promise<{ id: string }>;
};

/**
 * Render the edit form for one Project.
 *
 * @param props - Next route params.
 */
export default async function ProjectEditPage({ params }: ProjectEditPageProps) {
  const { id } = await params;
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
          href={`/projects/${id}`}
        >
          Back to the workspace
        </Link>
      </div>
      <section className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
        <ProjectEditForm projectId={id} />
      </section>
    </main>
  );
}
