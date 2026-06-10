"use client";

/**
 * Project Deliverable action for starting a Framework draft.
 *
 * The button only builds route state. Backend provenance is still enforced when
 * the Framework draft is created with `source_project_id`.
 */
import Link from "next/link";
import { FilePlusIcon } from "@radix-ui/react-icons";

type PublishAsFrameworkButtonProps = {
  deliverableId: string;
  description: string;
  fileKeys: string[];
  projectId: string;
  status: string;
  title: string;
};

/**
 * Build the existing Framework create route with deliverable prefill params.
 *
 * @param props - Approved Deliverable metadata from the workspace card.
 */
function buildFrameworkCreateHref({
  deliverableId,
  description,
  fileKeys,
  projectId,
  title,
}: PublishAsFrameworkButtonProps): string {
  const params = new URLSearchParams({
    description,
    source_deliverable_id: deliverableId,
    source_project_id: projectId,
    tags: "project-deliverable",
    title,
  });
  for (const fileKey of fileKeys) {
    params.append("file_keys", fileKey);
  }
  return `/dashboard/frameworks/new?${params.toString()}`;
}

/**
 * Render the publish-as-Framework action for approved Deliverables.
 *
 * @param props - Deliverable metadata and Project provenance identifiers.
 */
export function PublishAsFrameworkButton(props: PublishAsFrameworkButtonProps) {
  if (!["approved", "auto_approved"].includes(props.status)) {
    return null;
  }

  return (
    <Link
      className="inline-flex min-h-11 items-center justify-center gap-2 rounded-xl bg-foreground px-4 text-sm font-semibold text-background shadow-sm outline-none transition-all hover:bg-foreground/90 focus-visible:ring-2 focus-visible:ring-accent"
      href={buildFrameworkCreateHref(props)}
    >
      <FilePlusIcon aria-hidden className="h-4 w-4" />
      Publish as Framework
    </Link>
  );
}
