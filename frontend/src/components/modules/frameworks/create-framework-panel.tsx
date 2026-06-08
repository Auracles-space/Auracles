"use client";

/**
 * Create Framework panel.
 *
 * Handles draft creation and redirects to the edit workspace once the backend
 * creates the draft.
 */
import { useRouter } from "next/navigation";

import { FrameworkForm } from "@/components/modules/frameworks/framework-form";
import { createFramework } from "@/lib/generated/sdk.gen";
import type { FrameworkCreate } from "@/lib/generated/types.gen";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";

/**
 * Render create form for Contributor drafts.
 */
export function CreateFrameworkPanel() {
  const router = useRouter();

  async function handleCreate(payload: FrameworkCreate) {
    configureBrowserClient();
    const result = await createFramework({
      body: payload,
      headers: getAccessTokenHeaders(),
    });

    if (!result.response.ok || !result.data) {
      throw new Error(describeGeneratedError(result.error));
    }

    router.push(`/dashboard/frameworks/${result.data.id}`);
  }

  return <FrameworkForm onSubmit={handleCreate} submitLabel="Create draft" />;
}
