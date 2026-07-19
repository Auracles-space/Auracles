"use client";

/**
 * Confirmation-backed Project deletion control.
 *
 * Supports a compact icon treatment for Project cards and a labeled
 * destructive action for the Project workspace. The backend remains the
 * authority for commencement and pending-bid guards.
 */
import { TrashIcon } from "@radix-ui/react-icons";
import { useState } from "react";

import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { describeGeneratedError } from "@/lib/auth/form-client";
import { projectApi, type ProjectApiMode } from "@/lib/projects/project-api-mode";

type ProjectDeleteActionProps = {
  mode: ProjectApiMode;
  onDeleted: () => void;
  projectId: string;
  projectTitle: string;
  variant?: "button" | "icon";
};

/** Render a confirmed soft-delete action for one uncommenced Project. */
export function ProjectDeleteAction({
  mode,
  onDeleted,
  projectId,
  projectTitle,
  variant = "button",
}: ProjectDeleteActionProps) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleDelete(): Promise<void> {
    setBusy(true);
    setError(null);
    const result = await projectApi(mode).deleteProject(projectId);
    setBusy(false);
    if (!result.response.ok) {
      setError(describeGeneratedError(result.error));
      return;
    }
    setConfirming(false);
    onDeleted();
  }

  return (
    <>
      <button
        aria-label={variant === "icon" ? `Delete ${projectTitle}` : undefined}
        className={
          variant === "icon"
            ? "inline-flex min-h-11 min-w-11 items-center justify-center rounded-xl border border-error/40 bg-surface-1 text-error transition-colors hover:bg-error/10 focus-visible:ring-2 focus-visible:ring-error"
            : "inline-flex min-h-12 items-center justify-center gap-2 rounded-xl border border-error/50 px-4 py-2 text-sm font-semibold text-error transition-colors hover:bg-error/10 focus-visible:ring-2 focus-visible:ring-error"
        }
        onClick={() => {
          setError(null);
          setConfirming(true);
        }}
        type="button"
      >
        <TrashIcon aria-hidden="true" className="h-4 w-4" />
        {variant === "button" ? "Delete project" : null}
      </button>
      <ConfirmDialog
        busy={busy}
        confirmLabel={busy ? "Deleting..." : "Delete project"}
        description={
          <>
            Delete <strong>{projectTitle}</strong>? This removes it from Project
            listings. Projects with pending bids or commenced work cannot be deleted.
          </>
        }
        error={error}
        eyebrow="Project management"
        onClose={() => {
          if (!busy) {
            setConfirming(false);
          }
        }}
        onConfirm={() => void handleDelete()}
        open={confirming}
        title="Delete this project?"
        tone="danger"
      />
    </>
  );
}
