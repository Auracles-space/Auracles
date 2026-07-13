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
const AUTO_DISMISS_MS = 4500;

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
      // Auto-dismiss; the manual close button can remove it earlier.
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
      {toasts.map((toast) => {
        const isError = toast.tone === "error";
        return (
          <div
            key={toast.id}
            data-tone={toast.tone}
            className={[
              "pointer-events-auto flex w-full max-w-sm overflow-hidden rounded-2xl shadow-[0_12px_40px_rgba(0,0,0,0.35)] motion-safe:animate-[fade-in_140ms_ease-out]",
              // Dark pill regardless of app color scheme — intentionally opaque for legibility
              isError
                ? "bg-[#1c0a0a] border border-red-900/50"
                : "bg-[#061410] border border-emerald-900/40",
            ].join(" ")}
          >
            {/* Colored left accent stripe */}
            <div
              className={[
                "w-[3px] shrink-0",
                isError ? "bg-red-500" : "bg-emerald-500",
              ].join(" ")}
            />

            {/* Icon badge */}
            <div className="flex shrink-0 items-center px-4 py-4">
              {isError ? (
                <div className="flex h-8 w-8 items-center justify-center rounded-full bg-red-500/15">
                  <svg
                    xmlns="http://www.w3.org/2000/svg"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2.5"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    className="h-4 w-4 text-red-400"
                  >
                    <circle cx="12" cy="12" r="10" />
                    <line x1="15" y1="9" x2="9" y2="15" />
                    <line x1="9" y1="9" x2="15" y2="15" />
                  </svg>
                </div>
              ) : (
                <div className="flex h-8 w-8 items-center justify-center rounded-full bg-emerald-500/15">
                  <svg
                    xmlns="http://www.w3.org/2000/svg"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2.5"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    className="h-4 w-4 text-emerald-400"
                  >
                    <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
                    <polyline points="22 4 12 14.01 9 11.01" />
                  </svg>
                </div>
              )}
            </div>

            {/* Text: label + message */}
            <div className="flex min-w-0 flex-1 flex-col justify-center gap-0.5 py-4 pr-2">
              <p
                className={[
                  "text-[10px] font-bold uppercase tracking-widest",
                  isError ? "text-red-400" : "text-emerald-400",
                ].join(" ")}
              >
                {isError ? "Error" : "Success"}
              </p>
              <p className="min-w-0 break-words text-sm font-medium leading-snug text-white/85">
                {toast.message}
              </p>
            </div>

            {/* Dismiss button */}
            <button
              aria-label="Dismiss notification"
              className="inline-flex h-full shrink-0 items-center justify-center px-4 text-white/25 transition-colors hover:text-white/60 focus-visible:outline-none"
              onClick={() => onDismiss(toast.id)}
              type="button"
            >
              <svg
                xmlns="http://www.w3.org/2000/svg"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                className="h-3.5 w-3.5"
              >
                <line x1="18" y1="6" x2="6" y2="18" />
                <line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            </button>
          </div>
        );
      })}
    </div>
  );
}
