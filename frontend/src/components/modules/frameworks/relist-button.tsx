"use client";

/**
 * Contributor relist button.
 *
 * Returns a delisted Framework to the catalog at its current version without
 * re-running the pipeline (it already passed before it was published). For
 * content changes the contributor starts a new version instead. Calls the
 * backend `relist` endpoint behind a modal confirm.
 */
import { useRouter } from "next/navigation";
import { useState } from "react";

import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { relistFramework } from "@/lib/generated/sdk.gen";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";

type RelistButtonProps = {
  frameworkId: string;
  /** Called after a successful relist so the editor re-fetches its state. */
  onCompleted?: () => void;
};

/**
 * Render a confirmation-backed relist action.
 *
 * @param props - Framework id and completion hook.
 */
export function RelistButton({ frameworkId, onCompleted }: RelistButtonProps) {
  const router = useRouter();
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleRelist() {
    setBusy(true);
    setError(null);
    configureBrowserClient();
    const result = await relistFramework({
      headers: getAccessTokenHeaders(),
      path: { framework_id: frameworkId },
    });
    if (!result.response.ok) {
      setError(describeGeneratedError(result.error));
      setBusy(false);
      return;
    }
    setBusy(false);
    setConfirming(false);
    onCompleted?.();
    router.refresh();
  }

  return (
    <>
      <button
        className="inline-flex min-h-12 items-center justify-center rounded-xl bg-foreground px-4 py-2 text-sm font-semibold text-background shadow-sm transition hover:bg-foreground/90"
        onClick={() => setConfirming(true)}
        type="button"
      >
        Relist on marketplace
      </button>
      <ConfirmDialog
        open={confirming}
        eyebrow="Marketplace listing"
        title="Relist this framework?"
        description="Relisting returns this Framework to the catalog at its current version so operators can purchase it again. No pipeline re-check is needed. To change the content, start a new version instead."
        confirmLabel={busy ? "Relisting…" : "Relist framework"}
        busy={busy}
        error={error}
        onConfirm={handleRelist}
        onClose={() => setConfirming(false)}
      />
    </>
  );
}
