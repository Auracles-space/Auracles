"use client";

/**
 * Global step-up 2FA prompt.
 *
 * Mounted once in the root layout. Renders while the step-up gate has a
 * pending prompt (raised by the API interceptor on a 403 `step_up_required`),
 * verifies the code through `POST /v1/auth/step-up`, and settles the gate so
 * the interceptor can replay the original request. One verification opens a
 * 10-minute window, so the user is asked once per window, not per action.
 *
 * Also installs the interceptor on mount so generated-client calls from any
 * page benefit without per-form wiring.
 *
 * Maps to: docs/superpowers/specs/2026-09-13-step-up-and-admin-console-design.md §3.
 */
import { LockClosedIcon } from "@radix-ui/react-icons";
import { FormEvent, useEffect, useId, useRef, useState, useSyncExternalStore } from "react";
import { createPortal } from "react-dom";

import { TotpInput } from "@/components/modules/auth/totp-input";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import { settleStepUp, stepUpStore } from "@/lib/auth/step-up-gate";
import { installStepUpInterceptor } from "@/lib/auth/step-up-interceptor";
import { openStepUpV1AuthStepUpPost } from "@/lib/generated/sdk.gen";

function subscribe(listener: () => void): () => void {
  return stepUpStore.subscribe(listener);
}

function readPending(): boolean {
  return stepUpStore.getState().pending;
}

/**
 * Render the step-up prompt whenever the gate is waiting on the user.
 */
export function StepUpDialog() {
  const pending = useSyncExternalStore(subscribe, readPending, () => false);
  const [code, setCode] = useState("");
  const [useBackup, setUseBackup] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const titleId = useId();
  const backupId = useId();
  const backupRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    installStepUpInterceptor();
  }, []);

  // Reset the form each time a prompt opens so a stale code never lingers.
  useEffect(() => {
    if (pending) {
      setCode("");
      setUseBackup(false);
      setError(null);
      setBusy(false);
    }
  }, [pending]);

  useEffect(() => {
    if (!pending) {
      return;
    }
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        settleStepUp(false);
      }
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [pending]);

  if (!pending || typeof document === "undefined") {
    return null;
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = code.trim();
    if (trimmed.length < 6) {
      setError("Enter the full code.");
      return;
    }
    setBusy(true);
    setError(null);
    configureBrowserClient();
    let result;
    try {
      result = await openStepUpV1AuthStepUpPost({
        body: { code: trimmed },
        headers: getAccessTokenHeaders(),
      });
    } catch {
      setBusy(false);
      setError("The request could not be completed.");
      return;
    }
    if (!result.response.ok || !result.data) {
      setBusy(false);
      setError(describeGeneratedError(result.error));
      return;
    }
    settleStepUp(true, Date.parse(result.data.verified_until));
  }

  return createPortal(
    <div
      aria-labelledby={titleId}
      aria-modal="true"
      // Above every other overlay (confirm dialogs are z-50): the prompt is
      // raised from inside those flows and must be the thing the user sees.
      className="fixed inset-0 z-[60] grid place-items-end bg-black/40 p-0 motion-safe:animate-[fade-in_120ms_ease-out] sm:place-items-center sm:p-4"
      onClick={() => settleStepUp(false)}
      role="dialog"
    >
      <form
        className="w-full rounded-t-2xl border border-border-default bg-surface-1 p-5 shadow-bento sm:max-w-md sm:rounded-2xl"
        onClick={(event) => event.stopPropagation()}
        onSubmit={handleSubmit}
      >
        <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.05em] text-accent">
          <LockClosedIcon aria-hidden="true" className="h-3.5 w-3.5" />
          Sensitive action
        </p>
        <h2 className="mt-1 font-heading text-xl font-bold text-foreground" id={titleId}>
          Confirm it&apos;s you
        </h2>
        <p className="mt-2 text-sm leading-6 text-foreground-muted">
          Enter a code from your authenticator app. You will not be asked again for
          the next 10 minutes.
        </p>

        <div className="mt-4">
          {useBackup ? (
            <label className="block" htmlFor={backupId}>
              <span className="text-sm font-medium text-foreground">Backup code</span>
              <input
                autoComplete="one-time-code"
                className="mt-2 min-h-12 w-full rounded-xl border border-border-default bg-surface-2 px-4 py-2 text-center font-heading text-lg font-semibold tracking-[0.05em] text-foreground outline-none transition-colors placeholder:text-foreground-subtle focus-visible:border-accent focus-visible:ring-2 focus-visible:ring-accent"
                id={backupId}
                maxLength={16}
                onChange={(event) => setCode(event.target.value.trim())}
                placeholder="xxxx-xxxx"
                ref={backupRef}
                type="text"
                value={code}
              />
            </label>
          ) : (
            <TotpInput autoFocus onChange={setCode} value={code} />
          )}
        </div>

        {error ? (
          <p className="mt-3 text-sm text-error" role="alert">
            {error}
          </p>
        ) : null}

        <button
          className="mt-3 min-h-11 text-sm font-medium text-foreground-muted underline-offset-4 hover:text-foreground hover:underline"
          onClick={() => {
            setUseBackup((value) => !value);
            setCode("");
            setError(null);
          }}
          type="button"
        >
          {useBackup ? "Use my authenticator app" : "Use a backup code"}
        </button>

        <div className="mt-4 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <button
            className="min-h-12 rounded-xl border border-border-default bg-surface-1 px-5 py-2 text-sm font-semibold text-foreground transition hover:bg-surface-2"
            onClick={() => settleStepUp(false)}
            type="button"
          >
            Cancel
          </button>
          <button
            className="min-h-12 rounded-xl bg-foreground px-5 py-2 text-sm font-semibold text-background outline-none transition hover:bg-foreground/90 focus-visible:ring-2 focus-visible:ring-accent active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-60"
            disabled={busy}
            type="submit"
          >
            {busy ? "Verifying…" : "Verify"}
          </button>
        </div>
      </form>
    </div>,
    document.body,
  );
}
