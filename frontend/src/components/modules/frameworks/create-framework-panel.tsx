"use client";

/**
 * Create Framework panel.
 *
 * Handles draft creation and redirects to the edit workspace once the backend
 * creates the draft.
 */
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo } from "react";

import {
  FrameworkForm,
  type FrameworkDraftPrefill,
} from "@/components/modules/frameworks/framework-form";
import type { FrameworkCreate } from "@/lib/generated/types.gen";
import {
  frameworkApiFor,
  type FrameworkSeller,
} from "@/lib/frameworks/framework-api";

type FrameworkCreateWithProjectSource = FrameworkCreate & {
  source_project_id?: string | null;
};

export type ProjectDeliverablePrefill = FrameworkDraftPrefill & {
  sourceProjectId?: string;
};

type CreateFrameworkPanelProps = {
  seller: FrameworkSeller;
  basePath: string;
  prefill?: ProjectDeliverablePrefill;
};

/**
 * Render create form for Contributor drafts.
 *
 * @param props - Optional Project deliverable prefill values.
 */
export function CreateFrameworkPanel({
  seller,
  basePath,
  prefill = {},
}: CreateFrameworkPanelProps) {
  const router = useRouter();
  const api = useMemo(
    () => frameworkApiFor(seller),
    [seller],
  );

  async function handleCreate(payload: FrameworkCreate) {
    const body: FrameworkCreateWithProjectSource = {
      ...payload,
      ...(prefill.sourceProjectId
        ? { source_project_id: prefill.sourceProjectId }
        : {}),
    };
    const created = await api.create(body);
    router.push(`${basePath}/${created.id}`);
  }

  return (
    <div className="grid gap-4">
      <Link
        className="inline-flex min-h-11 w-fit items-center gap-1.5 text-sm font-semibold text-foreground-muted transition-colors hover:text-foreground"
        href={basePath}
      >
        <svg
          aria-hidden="true"
          className="h-4 w-4"
          fill="none"
          stroke="currentColor"
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth="2"
          viewBox="0 0 24 24"
        >
          <line x1="19" x2="5" y1="12" y2="12" />
          <polyline points="12 19 5 12 12 5" />
        </svg>
        Back to frameworks
      </Link>
      <FrameworkForm
        onSubmit={handleCreate}
        prefill={prefill}
        submitLabel="Create draft"
      />
    </div>
  );
}
