/**
 * Project workspace route.
 */
import { ProjectWorkspace } from "@/components/modules/projects/project-workspace";

type ProjectPageProps = {
  params: Promise<{ id: string }>;
};

/**
 * Render one Project workspace.
 *
 * @param props - Next route params.
 */
export default async function ProjectPage({ params }: ProjectPageProps) {
  const { id } = await params;
  return <ProjectWorkspace projectId={id} />;
}
