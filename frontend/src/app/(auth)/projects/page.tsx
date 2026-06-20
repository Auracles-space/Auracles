/**
 * Authenticated Projects landing page.
 */
import { Suspense } from "react";

import { ProjectListShell } from "@/components/modules/projects/project-list-shell";

/**
 * Render Operator and Contributor Project lists.
 *
 * Wrapped in Suspense because the shell reads the active tab from
 * `useSearchParams`, which requires a boundary during prerender.
 */
export default function ProjectsPage() {
  return (
    <Suspense>
      <ProjectListShell />
    </Suspense>
  );
}
