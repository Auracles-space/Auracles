"use client";

/**
 * Create Framework panel.
 *
 * Handles draft creation and redirects to the edit workspace once the backend
 * creates the draft.
 */
import { useRouter } from "next/navigation";

import {
  FrameworkForm,
  type FrameworkDraftPrefill,
} from "@/components/modules/frameworks/framework-form";
import { createFramework } from "@/lib/generated/sdk.gen";
import type { FrameworkCreate } from "@/lib/generated/types.gen";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";

type FrameworkCreateWithProjectSource = FrameworkCreate & {
  source_project_id?: string;
};

export type ProjectDeliverablePrefill = FrameworkDraftPrefill & {
  sourceProjectId?: string;
};

type CreateFrameworkPanelProps = {
  prefill?: ProjectDeliverablePrefill;
};

/**
 * Render create form for Contributor drafts.
 *
 * @param props - Optional Project deliverable prefill values.
 */
export function CreateFrameworkPanel({ prefill = {} }: CreateFrameworkPanelProps) {
  const router = useRouter();

  async function handleCreate(payload: FrameworkCreate) {
    configureBrowserClient();
    const body: FrameworkCreateWithProjectSource = {
      ...payload,
      ...(prefill.sourceProjectId
        ? { source_project_id: prefill.sourceProjectId }
        : {}),
    };
    const result = await createFramework({
      body,
      headers: getAccessTokenHeaders(),
    });

    if (!result.response.ok || !result.data) {
      throw new Error(describeGeneratedError(result.error));
    }

    router.push(`/dashboard/frameworks/${result.data.id}`);
  }

  return (
    <FrameworkForm
      onSubmit={handleCreate}
      prefill={prefill}
      submitLabel="Create draft"
    />
  );
}
