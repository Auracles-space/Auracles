/**
 * Project workspace route.
 */
import { Suspense } from "react";

import { ProjectWorkspace } from "@/components/modules/projects/project-workspace";

type ProjectPageProps = {
  params: Promise<{ id: string }>;
};

/**
 * Render one Project workspace.
 *
 * Wrapped in Suspense because the workspace reads the active tab from
 * `useSearchParams`, which requires a boundary during prerender.
 *
 * @param props - Next route params.
 */
export default async function ProjectPage({ params }: ProjectPageProps) {
  const { id } = await params;
  return (
    <Suspense>
      <ProjectWorkspace projectId={id} />
    </Suspense>
  );
}
