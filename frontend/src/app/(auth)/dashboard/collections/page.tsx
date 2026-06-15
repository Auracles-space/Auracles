/**
 * Contributor Collection dashboard route.
 *
 * Hosts the bundle builder for creating, composing, publishing, and unpublishing
 * Framework Collections.
 */
import { CollectionBuilder } from "@/components/modules/collections/collection-builder";

/**
 * Render Contributor-owned Collections.
 */
export default function ContributorCollectionsPage() {
  return (
    <main className="px-4 py-8 text-foreground md:px-8">
      <div className="mx-auto max-w-[1280px]">
        <header className="mb-6 rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm md:p-8">
          <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
            Contributor dashboard
          </p>
          <h1 className="mt-2 font-heading text-3xl font-bold text-foreground md:text-4xl">
            Collections
          </h1>
          <p className="mt-3 max-w-2xl text-sm leading-6 text-foreground-muted">
            Bundle published Frameworks into discounted Collections for
            marketplace operators.
          </p>
        </header>
        <CollectionBuilder />
      </div>
    </main>
  );
}
