/**
 * Contributor Framework dashboard route.
 */
import Link from "next/link";
import { PlusIcon } from "@radix-ui/react-icons";

import { FrameworkList } from "@/components/modules/frameworks/framework-list";

/**
 * Render Contributor-owned Frameworks.
 */
export default function ContributorFrameworksPage() {
  return (
    <main className="px-4 py-8 text-foreground md:px-8">
      <div className="mx-auto w-full max-w-[1280px]">
        <header className="mb-10 flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.08em] text-accent">
              Contributor dashboard
            </p>
            <h1 className="mt-2 font-heading text-3xl font-bold tracking-[-0.02em] text-foreground md:text-4xl">
              Frameworks
            </h1>
            <p className="mt-2 max-w-xl text-sm leading-6 text-foreground-muted">
              Manage, version, and monitor the publication and review pipelines for your reusable operational frameworks.
            </p>
          </div>
          <Link
            className="inline-flex min-h-12 items-center justify-center gap-2 rounded-xl bg-foreground px-5 py-2.5 text-sm font-semibold text-background shadow-sm outline-none transition-all hover:opacity-90 focus-visible:ring-2 focus-visible:ring-accent"
            href="/dashboard/frameworks/new"
          >
            <PlusIcon className="h-4 w-4 stroke-[1.5]" />
            Create framework
          </Link>
        </header>
        <FrameworkList />
      </div>
    </main>
  );
}
