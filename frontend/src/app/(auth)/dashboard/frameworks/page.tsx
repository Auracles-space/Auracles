/**
 * Contributor Framework dashboard route.
 *
 * Hosts Frameworks and Collections as two tabs of one workspace.
 */
import { Suspense } from "react";

import { ContributorWorkspace } from "@/components/modules/frameworks/contributor-workspace";

/**
 * Render the Contributor workspace.
 *
 * Suspense satisfies `useSearchParams` in the workspace, which reads the
 * `tab` the URL asks for.
 */
export default function ContributorFrameworksPage() {
  return (
    <main className="px-4 py-8 text-foreground md:px-8">
      <Suspense fallback={null}>
        <ContributorWorkspace />
      </Suspense>
    </main>
  );
}
