"use client";

/**
 * Per-account active-Project ceiling control.
 *
 * BR-PROJ-004 caps an Operator at five concurrent active Projects. The number
 * bounds how much escrow one account can have in flight, so it is lifted for a
 * single account rather than amended for everyone — this form is that grant.
 *
 * Removing the grant sends `null`, not the current default: the account goes
 * back to following the business rule, including a later change to it, instead
 * of being pinned to today's five.
 *
 * Lives in its own file because the directory panel it expands inside is
 * already well past the size a component should be.
 */
import React, { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import { setUserProjectCapV1AdminUsersUserIdProjectCapPatch } from "@/lib/generated/sdk.gen";

/** Props for the per-account Project ceiling form. */
export type AdminUserProjectCapFormProps = {
  /** The Operator whose ceiling is being changed. */
  userId: string;
  /** Their current ceiling, or null when they follow the default. */
  current: number | null;
  /** Called with the saved ceiling so the directory row can update. */
  onSaved: (maxActiveProjects: number | null) => void;
  /** Called when the admin dismisses the form without saving. */
  onCancel: () => void;
};

/**
 * Render the raise/clear controls for one Operator's Project ceiling.
 *
 * @param props - The target account, its current ceiling, and the callbacks.
 */
export function AdminUserProjectCapForm({
  userId,
  current,
  onSaved,
  onCancel,
}: AdminUserProjectCapFormProps) {
  const [limit, setLimit] = useState(current === null ? "" : String(current));
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  /**
   * Send one ceiling change.
   *
   * @param maxActiveProjects - The new ceiling, or null to follow the default.
   */
  async function save(maxActiveProjects: number | null): Promise<void> {
    setBusy(true);
    setError(null);
    configureBrowserClient();
    const result = await setUserProjectCapV1AdminUsersUserIdProjectCapPatch({
      body: { max_active_projects: maxActiveProjects, reason: reason.trim() },
      headers: getAccessTokenHeaders(),
      path: { user_id: userId },
    });
    setBusy(false);

    if (!result.response.ok || !result.data) {
      setError(describeGeneratedError(result.error));
      return;
    }
    onSaved(result.data.max_active_projects);
  }

  const parsed = Number.parseInt(limit, 10);
  const limitIsValid = Number.isInteger(parsed) && parsed >= 1 && parsed <= 500;
  const reasonGiven = reason.trim().length > 0;

  return (
    <div className="col-span-full mt-4 grid gap-4 rounded-xl border border-border-default bg-surface-2 p-4 text-left">
      <p className="text-sm leading-6 text-foreground-muted">
        An Operator may hold five concurrent active Projects by default. Raise
        this only for an account whose load is understood: the limit bounds how
        much escrow one account can have in flight at once.
      </p>
      <label className="grid gap-2 text-sm font-semibold text-foreground">
        Concurrent active Projects
        <input
          className="min-h-12 rounded-xl border border-border-default bg-background px-4 text-sm text-foreground outline-none transition-colors focus-visible:ring-2 focus-visible:ring-accent"
          inputMode="numeric"
          max={500}
          min={1}
          onChange={(event) => setLimit(event.target.value)}
          placeholder="5"
          type="number"
          value={limit}
        />
      </label>
      <label className="grid gap-2 text-sm font-semibold text-foreground">
        Why this account
        <textarea
          className="min-h-24 rounded-xl border border-border-default bg-background px-4 py-3 text-sm text-foreground outline-none transition-colors focus-visible:ring-2 focus-visible:ring-accent"
          onChange={(event) => setReason(event.target.value)}
          placeholder="Recorded in the audit trail alongside the old and new limits"
          value={reason}
        />
      </label>

      {error ? (
        <p className="rounded-xl border border-error/30 bg-error/10 p-3 text-sm text-error">
          {error}
        </p>
      ) : null}

      <div className="flex flex-wrap gap-3">
        <Button
          disabled={busy || !limitIsValid || !reasonGiven}
          onClick={() => void save(parsed)}
        >
          Save limit
        </Button>
        {current !== null ? (
          <Button
            disabled={busy || !reasonGiven}
            onClick={() => void save(null)}
            variant="destructive"
          >
            Remove exception
          </Button>
        ) : null}
        <Button onClick={onCancel} variant="secondary">
          Cancel
        </Button>
      </div>
    </div>
  );
}
