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
import { useToast } from "@/components/ui/toast";

type PublishButtonProps = {
  disabled?: boolean;
  frameworkId: string;
  /**
   * Called after a successful publish. The editor uses this to re-fetch its
   * client-held framework state — `router.refresh()` alone does not re-run a
   * client component's mount fetch, so the post-publish status would otherwise
   * stay stale and the Publish button would linger.
   */
  onCompleted?: () => void;
};

/**
 * Render a publish action for a pipeline-passed Framework.
 *
 * @param props - Framework id, advisory disabled state, and completion hook.
 */
export function PublishButton({
  disabled = false,
  frameworkId,
  onCompleted,
}: PublishButtonProps) {
  const router = useRouter();
  const toast = useToast();
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
    // Publishing flips the status banner at the top of a long editor and
    // unmounts this button, so a toast is the only feedback the Contributor
    // reliably sees where their cursor is.
    toast.success("Framework published.");
    onCompleted?.();
    router.refresh();
  }

  return (
    <div>
      <button
        className="inline-flex min-h-12 items-center justify-center rounded-xl bg-foreground px-4 py-2 text-sm font-semibold text-background transition hover:bg-foreground/90 disabled:opacity-60"
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
