import { OrgOperatorLibrary } from "@/components/modules/library/org-operator-library";

export default async function OrgLibraryPage({
  params,
}: {
  params: Promise<{ orgId: string }>;
}) {
  const { orgId } = await params;

  return (
    <div>
      <div className="mb-6">
        <h2 className="font-heading text-2xl font-bold text-foreground">
          Organization Library
        </h2>
        <p className="mt-1 text-sm text-foreground-muted">
          Frameworks licensed for this organization.
        </p>
      </div>
      <OrgOperatorLibrary orgId={orgId} />
    </div>
  );
}
