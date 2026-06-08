"use client";

/**
 * Contributor publish button.
 *
 * Calls the backend publish gate. UI enablement is advisory; the backend still
 * enforces every pipeline rule before publication.
 */
import { useRouter } from "next/navigation";
import { useState } from "react";

import { publishFramework } from "@/lib/generated/sdk.gen";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";

type PublishButtonProps = {
  disabled?: boolean;
  frameworkId: string;
};

/**
 * Render a publish action for a pipeline-passed Framework.
 *
 * @param props - Framework id and advisory disabled state.
 */
export function PublishButton({ disabled = false, frameworkId }: PublishButtonProps) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handlePublish() {
    configureBrowserClient();
    setSubmitting(true);
    setError(null);
    const result = await publishFramework({
      headers: getAccessTokenHeaders(),
      path: { framework_id: frameworkId },
    });

    setSubmitting(false);
    if (!result.response.ok) {
      setError(describeGeneratedError(result.error));
      return;
    }
    router.refresh();
  }

  return (
    <div>
      <button
        className="inline-flex min-h-11 items-center justify-center rounded-[6px] bg-foreground px-4 py-2 text-sm font-semibold text-background transition hover:bg-foreground/90 disabled:opacity-60"
        disabled={disabled || submitting}
        onClick={handlePublish}
        type="button"
      >
        {submitting ? "Publishing" : "Publish"}
      </button>
      {error ? <p className="mt-2 text-sm text-error">{error}</p> : null}
    </div>
  );
}
