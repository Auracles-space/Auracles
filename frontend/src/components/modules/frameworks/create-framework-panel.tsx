"use client";

/**
 * Create Framework panel.
 *
 * Handles onboarding-aware draft creation and redirects to the edit workspace
 * once the backend creates the draft.
 */
import { usePathname, useRouter } from "next/navigation";

import { FrameworkForm } from "@/components/modules/frameworks/framework-form";
import { createFramework } from "@/lib/generated/sdk.gen";
import type { FrameworkCreate } from "@/lib/generated/types.gen";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import { resolveMarketplaceActionRedirect } from "@/lib/marketplace/action-redirect";

/**
 * Render create form for Contributor drafts.
 */
export function CreateFrameworkPanel() {
  const pathname = usePathname();
  const router = useRouter();

  async function handleCreate(payload: FrameworkCreate) {
    configureBrowserClient();
    const result = await createFramework({
      body: payload,
      headers: getAccessTokenHeaders(),
    });

    const redirect = resolveMarketplaceActionRedirect({
      error: result.error,
      pathname,
    });
    if (redirect) {
      window.location.assign(redirect);
      return;
    }

    if (!result.response.ok || !result.data) {
      throw new Error(describeGeneratedError(result.error));
    }

    router.push(`/dashboard/frameworks/${result.data.id}`);
  }

  return <FrameworkForm onSubmit={handleCreate} submitLabel="Create draft" />;
}
