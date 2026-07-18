/**
 * Contributor Framework edit route.
 */
import { FrameworkEditor } from "@/components/modules/frameworks/framework-editor";

type FrameworkEditPageProps = {
  params: Promise<{ id: string }>;
};

/**
 * Render the Framework workspace for one owned Framework.
 *
 * @param props - Next.js route params.
 */
export default async function FrameworkEditPage({
  params,
}: FrameworkEditPageProps) {
  const { id } = await params;

  return (
    <main className="px-4 py-8 text-foreground md:px-8">
      <div className="mx-auto max-w-[1280px]">
        <FrameworkEditor
          basePath="/dashboard/frameworks"
          canManageLiveState
          frameworkId={id}
          seller={{ kind: "user" }}
        />
      </div>
    </main>
  );
}
