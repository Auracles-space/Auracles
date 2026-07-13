"use client";

/**
 * Global toast notifications.
 *
 * A lightweight, dependency-free notification system for surfacing the outcome
 * of an action whose visible result lands off-screen from the control that
 * triggered it — e.g. publishing a Framework from the bottom of a long editor
 * flips a status banner at the very top. Inline feedback is preferred wherever
 * the result is already in view (login, small forms); toasts fill the gap for
 * long-scroll flows only.
 *
 * `ToastProvider` mounts once at the app root and exposes `useToast()` to any
 * client component beneath it. The viewport is an `aria-live` region so screen
 * readers announce outcomes without a focus change.
 */
import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

/** Visual + semantic tone of a toast. */
type ToastTone = "success" | "error";

/** A single queued toast. */
type ToastItem = {
  id: number;
  message: string;
  tone: ToastTone;
};

/** Public API handed to consumers via `useToast()`. */
type ToastApi = {
  /** Announce a successful outcome. */
  success: (message: string) => void;
  /** Announce a failed outcome. */
  error: (message: string) => void;
};

/** How long a toast stays before auto-dismissing, in milliseconds. */
const AUTO_DISMISS_MS = 4000;

const ToastContext = createContext<ToastApi | null>(null);

/**
 * Provide toast state and render the live-region viewport.
 *
 * Wrap the app once (root layout). Children gain access to `useToast()`.
 *
 * @param props - React children rendered beneath the provider.
 */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  // Monotonic id source so repeated identical messages stay distinct entries.
  const nextId = useRef(0);

  const dismiss = useCallback((id: number) => {
    setToasts((current) => current.filter((toast) => toast.id !== id));
  }, []);

  const push = useCallback(
    (message: string, tone: ToastTone) => {
      const id = nextId.current;
      nextId.current += 1;
      setToasts((current) => [...current, { id, message, tone }]);
      // Auto-dismiss; the manual control can still remove it earlier.
      setTimeout(() => dismiss(id), AUTO_DISMISS_MS);
    },
    [dismiss],
  );

  const api = useMemo<ToastApi>(
    () => ({
      success: (message) => push(message, "success"),
      error: (message) => push(message, "error"),
    }),
    [push],
  );

  return (
    <ToastContext.Provider value={api}>
      {children}
      <ToastViewport toasts={toasts} onDismiss={dismiss} />
    </ToastContext.Provider>
  );
}

/**
 * Access the toast API. Must be called beneath a `ToastProvider`.
 *
 * @returns The `success` / `error` announcers.
 * @throws Error when used outside a `ToastProvider`.
 */
export function useToast(): ToastApi {
  const context = useContext(ToastContext);
  if (!context) {
    throw new Error("useToast must be used within a ToastProvider.");
  }
  return context;
}

/**
 * Render the stacked toast viewport as an `aria-live` region.
 *
 * Bottom-center on mobile, bottom-right from `sm:` up. The wrapper is
 * click-through; only the toast cards capture pointer events.
 *
 * @param props - Current toasts and the dismiss callback.
 */
function ToastViewport({
  toasts,
  onDismiss,
}: {
  toasts: ToastItem[];
  onDismiss: (id: number) => void;
}) {
  if (toasts.length === 0) {
    return null;
  }

  return (
    <div
      aria-live="polite"
      className="pointer-events-none fixed inset-x-0 bottom-0 z-[60] flex flex-col items-center gap-2 p-4 sm:inset-x-auto sm:right-0 sm:items-end"
      role="status"
    >
      {toasts.map((toast) => (
        <div
          className={`pointer-events-auto flex w-full max-w-sm items-start gap-3 rounded-xl border bg-surface-1 px-4 py-3 shadow-xl motion-safe:animate-[fade-in_120ms_ease-out] ${
            toast.tone === "error" ? "border-error" : "border-accent"
          }`}
          data-tone={toast.tone}
          key={toast.id}
        >
          <span
            aria-hidden="true"
            className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${
              toast.tone === "error" ? "bg-error" : "bg-accent"
            }`}
          />
          <p className="min-w-0 flex-1 break-words text-sm text-foreground">
            {toast.message}
          </p>
          <button
            aria-label="Dismiss notification"
            className="-mr-1 -mt-1 inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-lg text-lg leading-none text-foreground-muted transition hover:bg-surface-2 hover:text-foreground"
            onClick={() => onDismiss(toast.id)}
            type="button"
          >
            <span aria-hidden="true">×</span>
          </button>
        </div>
      ))}
    </div>
  );
}
