"use client";

/**
 * Contributor delist button.
 *
 * UI says "Delist from marketplace" even though the backend endpoint is named
 * `unpublish`; existing licensees keep access to purchased versions. The
 * confirm step runs in a modal dialog so the consequence is read before the
 * action commits.
 */
import { useRouter } from "next/navigation";
import { useState } from "react";

import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { unpublishFramework } from "@/lib/generated/sdk.gen";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";

type DelistButtonProps = {
  frameworkId: string;
  /** Called after a successful delist so the editor re-fetches its state. */
  onCompleted?: () => void;
};

/**
 * Render a confirmation-backed delist action.
 *
 * @param props - Framework id and completion hook.
 */
export function DelistButton({ frameworkId, onCompleted }: DelistButtonProps) {
  const router = useRouter();
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleDelist() {
    setBusy(true);
    setError(null);
    configureBrowserClient();
    const result = await unpublishFramework({
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
        className="inline-flex min-h-12 items-center justify-center rounded-xl border border-error px-4 py-2 text-sm font-semibold text-error transition hover:bg-error/10"
        onClick={() => setConfirming(true)}
        type="button"
      >
        Delist from marketplace
      </button>
      <ConfirmDialog
        open={confirming}
        eyebrow="Marketplace listing"
        title="Delist this framework?"
        description="Delisting hides this Framework from the catalog so no new operators can purchase it. Existing licensees keep access to the version they paid for. You can relist it anytime."
        confirmLabel={busy ? "Delisting…" : "Delist framework"}
        tone="danger"
        busy={busy}
        error={error}
        onConfirm={handleDelist}
        onClose={() => setConfirming(false)}
      />
    </>
  );
}
