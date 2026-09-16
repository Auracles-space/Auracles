"use client";

/**
 * Reusable confirmation dialog.
 *
 * A focus-trapped overlay used to gate a consequential action (delisting,
 * relisting) behind an explicit confirm step. Renders as a bottom sheet on
 * mobile and a centered card from `sm:` up, matching the payout request modal.
 * Closes on Escape, backdrop click, or Cancel. Respects reduced motion.
 */
import { ReactNode, useEffect, useId, useRef } from "react";
import { createPortal } from "react-dom";

type ConfirmTone = "default" | "danger";

type ConfirmDialogProps = {
  /** Whether the dialog is mounted and visible. */
  open: boolean;
  /** Short dialog heading describing the action. */
  title: string;
  /** Small eyebrow label above the title. */
  eyebrow?: string;
  /** Body copy explaining the consequence of confirming. */
  description: ReactNode;
  /** Label for the confirm button (active voice, e.g. "Delist framework"). */
  confirmLabel: string;
  /** Label for the dismiss button. */
  cancelLabel?: string;
  /** Visual tone — `danger` styles the confirm button as destructive. */
  tone?: ConfirmTone;
  /** Disables the confirm button (e.g. while the request is in flight). */
  busy?: boolean;
  /**
   * Disables the confirm button without the in-flight styling — for dialogs
   * whose action is gated on input (a typed confirmation phrase, a reason).
   */
  confirmDisabled?: boolean;
  /** Optional inline error shown above the action row. */
  error?: string | null;
  /** Called when the user confirms the action. */
  onConfirm: () => void;
  /** Called when the user dismisses the dialog. */
  onClose: () => void;
};

/**
 * Render a confirm/cancel modal dialog.
 *
 * @param props - Open state, copy, tone, and confirm/close callbacks.
 */
export function ConfirmDialog({
  open,
  title,
  eyebrow,
  description,
  confirmLabel,
  cancelLabel = "Cancel",
  tone = "default",
  busy = false,
  confirmDisabled = false,
  error = null,
  onConfirm,
  onClose,
}: ConfirmDialogProps) {
  const titleId = useId();
  const confirmRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  // Callers usually pass an inline onClose, which changes identity on every
  // render. Reading it through a ref keeps the open effect (and its focus
  // move) tied to `open` alone, so typing in a field does not steal focus.
  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  // Close on Escape and move focus to the confirm button on open so keyboard
  // users land inside the dialog rather than behind it.
  useEffect(() => {
    if (!open) {
      return;
    }
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        onCloseRef.current();
      }
    }
    document.addEventListener("keydown", handleKeyDown);
    // A dialog that asks for input (e.g. a reason) opens with confirm
    // disabled; focus then goes to the first field so typing can start.
    const confirm = confirmRef.current;
    if (confirm && !confirm.disabled) {
      confirm.focus();
    } else {
      panelRef.current
        ?.querySelector<HTMLElement>("input, textarea, select, button:not([disabled])")
        ?.focus();
    }
    return () => document.removeEventListener("keydown", handleKeyDown);
    // busy is intentionally omitted: refocusing on every busy flip would yank
    // the cursor out of a field the user is typing in.
  }, [open]);

  if (!open || typeof document === "undefined") {
    return null;
  }

  const confirmClasses =
    tone === "danger"
      ? "border border-error bg-error text-background hover:bg-error/90"
      : "bg-foreground text-background hover:bg-foreground/90";

  // Portal to the body so the fixed overlay escapes any ancestor stacking
  // context (e.g. the app shell's `relative z-20` main), letting it cover the
  // sticky header instead of rendering beneath it.
  return createPortal(
    <div
      aria-labelledby={titleId}
      aria-modal="true"
      className="fixed inset-0 z-50 grid place-items-end bg-black/40 p-0 motion-safe:animate-[fade-in_120ms_ease-out] sm:place-items-center sm:p-4"
      onClick={onClose}
      role="dialog"
    >
      <div
        className="w-full rounded-t-2xl border border-border-default bg-surface-1 p-5 shadow-xl sm:max-w-md sm:rounded-2xl"
        onClick={(event) => event.stopPropagation()}
        ref={panelRef}
      >
        {eyebrow ? (
          <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
            {eyebrow}
          </p>
        ) : null}
        <h2
          className="mt-1 font-heading text-xl font-bold text-foreground"
          id={titleId}
        >
          {title}
        </h2>
        <div className="mt-2 text-sm text-foreground-muted">{description}</div>

        {error ? (
          <p className="mt-3 text-sm text-error">{error}</p>
        ) : null}

        <div className="mt-5 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <button
            className="min-h-12 rounded-xl border border-border-default px-5 py-2 text-sm font-semibold text-foreground transition hover:bg-surface-2"
            onClick={onClose}
            type="button"
          >
            {cancelLabel}
          </button>
          <button
            className={`min-h-12 rounded-xl px-5 py-2 text-sm font-semibold shadow-sm outline-none transition focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-60 ${confirmClasses}`}
            aria-busy={busy || undefined}
            disabled={busy || confirmDisabled}
            onClick={onConfirm}
            ref={confirmRef}
            type="button"
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
