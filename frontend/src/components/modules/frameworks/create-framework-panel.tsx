"use client";

/**
 * Create Framework panel.
 *
 * Handles draft creation and redirects to the edit workspace once the backend
 * creates the draft.
 */
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
    <FrameworkForm
      onSubmit={handleCreate}
      prefill={prefill}
      submitLabel="Create draft"
    />
  );
}
