/**
 * Contributor Framework creation route.
 */
import { CreateFrameworkPanel } from "@/components/modules/frameworks/create-framework-panel";

/**
 * Render the new Framework wizard.
 */
export default function NewFrameworkPage() {
  return (
    <main className="min-h-screen bg-background px-4 py-8 text-foreground md:px-8">
      <div className="mx-auto max-w-3xl">
        <header className="mb-8">
          <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
            New framework
          </p>
          <h1 className="mt-2 font-heading text-3xl font-bold text-foreground">
            Create a draft
          </h1>
          <p className="mt-3 text-sm leading-6 text-foreground-muted">
            Complete metadata first, then upload artifacts and submit to the
            processing pipeline.
          </p>
        </header>
        <section className="rounded-[8px] border border-border-default bg-surface-1 p-5">
          <CreateFrameworkPanel />
        </section>
      </div>
    </main>
  );
}
