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
import { useToast } from "@/components/ui/toast";
import type { FrameworkApi } from "@/lib/frameworks/framework-api";

type RelistButtonProps = {
  api: FrameworkApi;
  frameworkId: string;
  /** Called after a successful relist so the editor re-fetches its state. */
  onCompleted?: () => void;
};

/**
 * Render a confirmation-backed relist action.
 *
 * @param props - Framework id and completion hook.
 */
export function RelistButton({ api, frameworkId, onCompleted }: RelistButtonProps) {
  const router = useRouter();
  const toast = useToast();
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleRelist() {
    setBusy(true);
    setError(null);
    try {
      await api.relist(frameworkId);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Relist failed.");
      setBusy(false);
      return;
    }
    setBusy(false);
    setConfirming(false);
    // The modal closes and the status banner flips at the top of the page, so
    // confirm the outcome with a toast that stays in the Contributor's view.
    toast.success("Framework relisted.");
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
