/**
 * Operator Project creation page.
 */
import { ProjectCreateForm } from "@/components/modules/projects/project-create-form";

/**
 * Render the Project creation workspace.
 */
export default function NewProjectPage() {
  return (
    <main className="mx-auto grid max-w-4xl gap-8 px-4 py-10 text-foreground md:px-8">
      <div>
        <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
          New Project
        </p>
        <h1 className="mt-2 font-heading text-3xl font-bold">Post a Project</h1>
        <p className="mt-3 text-sm leading-6 text-foreground-muted">
          Define the scope, budget, and first deliverable so Contributors can
          submit precise proposals.
        </p>
      </div>
      <section className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
        <ProjectCreateForm />
      </section>
    </main>
  );
}
