/**
 * Contributor Framework dashboard route.
 */
import Link from "next/link";

import { FrameworkList } from "@/components/modules/frameworks/framework-list";

/**
 * Render Contributor-owned Frameworks.
 */
export default function ContributorFrameworksPage() {
  return (
    <main className="min-h-screen bg-background px-4 py-8 text-foreground md:px-8">
      <div className="mx-auto max-w-[1280px]">
        <header className="mb-8 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
              Contributor dashboard
            </p>
            <h1 className="mt-2 font-heading text-3xl font-bold text-foreground">
              Frameworks
            </h1>
          </div>
          <Link
            className="inline-flex min-h-11 items-center justify-center rounded-[6px] bg-foreground px-4 py-2 text-sm font-semibold text-background transition hover:bg-foreground/90"
            href="/dashboard/frameworks/new"
          >
            Create framework
          </Link>
        </header>
        <FrameworkList />
      </div>
    </main>
  );
}
