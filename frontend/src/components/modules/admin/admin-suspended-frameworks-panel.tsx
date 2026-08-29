"use client";

/**
 * Admin suspended-frameworks panel.
 *
 * Lists Frameworks an admin has taken down from the marketplace and lets an
 * admin reverse a takedown (reinstate), returning the Framework to the public
 * catalog. Reinstatement is the only path back to published — a Contributor
 * cannot republish a suspended Framework.
 *
 * Maps to: admin content moderation (FR-ADMIN, FR-FWK).
 */
import { useEffect, useState } from "react";

import { TotpInput } from "@/components/modules/auth/totp-input";
import { Button } from "@/components/ui/button";
import { TableSkeleton } from "@/components/ui/skeletons/table-skeleton";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import {
  listSuspendedFrameworksV1AdminFrameworksSuspendedGet,
  reinstateFrameworkV1AdminFrameworksFrameworkIdReinstatePost,
} from "@/lib/generated/sdk.gen";
import type { AdminSuspendedFrameworkItem } from "@/lib/generated/types.gen";

/**
 * Format an ISO timestamp for display, falling back to the raw value.
 *
 * @param value - ISO timestamp string, or null when unknown.
 */
function formatTimestamp(value: string | null | undefined): string {
  if (!value) {
    return "Unknown date";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(parsed);
}

/**
 * Render the list of suspended Frameworks with per-row reinstate controls.
 */
export function AdminSuspendedFrameworksPanel() {
  const [items, setItems] = useState<AdminSuspendedFrameworkItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [totpCode, setTotpCode] = useState("");

  const canAct = totpCode.trim().length >= 6;

  useEffect(() => {
    let mounted = true;

    async function loadSuspended(): Promise<void> {
      configureBrowserClient();
      const result = await listSuspendedFrameworksV1AdminFrameworksSuspendedGet({
        headers: getAccessTokenHeaders(),
      });
      if (!mounted) {
        return;
      }
      setLoading(false);
      if (!result.response.ok || !result.data) {
        setError(describeGeneratedError(result.error));
        return;
      }
      setError(null);
      setItems(result.data.items);
    }

    void loadSuspended();
    return () => {
      mounted = false;
    };
  }, []);

  async function handleReinstate(frameworkId: string): Promise<void> {
    setBusyId(frameworkId);
    setError(null);
    configureBrowserClient();
    const result = await reinstateFrameworkV1AdminFrameworksFrameworkIdReinstatePost({
      body: { totp_code: totpCode.trim() },
      headers: getAccessTokenHeaders(),
      path: { framework_id: frameworkId },
    });
    setBusyId(null);
    if (!result.response.ok || !result.data) {
      setError(describeGeneratedError(result.error));
      return;
    }
    // Each code is single-use, so clear it rather than leave a stale value
    // that would silently fail the next reinstatement.
    setTotpCode("");
    // Drop the reinstated Framework from the suspended list.
    setItems((current) =>
      current.filter((item) => item.framework_id !== frameworkId),
    );
  }

  if (loading) {
    return <TableSkeleton />;
  }

  return (
    <section className="rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm md:p-6">
      <div className="flex flex-col gap-1">
        <h2 className="font-heading text-xl font-bold text-foreground">
          Suspended frameworks
        </h2>
        <p className="text-sm text-foreground-muted">
          Frameworks removed from the marketplace. Reinstating returns one to the
          public catalog after re-running trust checks.
        </p>
      </div>

      {error ? (
        <p className="mt-4 rounded-xl border border-error/30 bg-error/10 p-3 text-sm text-error">
          {error}
        </p>
      ) : null}

      {items.length === 0 ? (
        <p className="mt-6 rounded-xl border border-border-default bg-surface-2 p-4 text-sm text-foreground-muted">
          No frameworks are currently suspended.
        </p>
      ) : (
        <>
          <div className="mt-5 rounded-xl border border-border-default bg-surface-2 p-4">
            <TotpInput onChange={setTotpCode} value={totpCode} />
            <p className="mt-2 text-xs leading-5 text-foreground-muted">
              Returning a Framework to the public catalog needs a current code.
            </p>
          </div>
          <ul className="mt-3 grid gap-3">
          {items.map((item) => (
            <li
              key={item.framework_id}
              className="flex flex-col gap-3 rounded-xl border border-border-default bg-surface-2 p-4 md:flex-row md:items-center md:justify-between"
            >
              <div className="min-w-0">
                <p className="truncate font-semibold text-foreground">
                  {item.title}
                </p>
                <p className="mt-0.5 text-xs text-foreground-muted">
                  {item.contributor_name} · Suspended{" "}
                  {formatTimestamp(item.suspended_at)}
                </p>
                {item.reason ? (
                  <p className="mt-1 text-sm text-foreground">
                    <span className="font-semibold">Reason:</span> {item.reason}
                  </p>
                ) : null}
              </div>
              <Button
                variant="secondary"
                className="w-full md:w-auto"
                loading={busyId === item.framework_id}
                disabled={busyId !== null || !canAct}
                onClick={() => void handleReinstate(item.framework_id)}
              >
                Reinstate
              </Button>
            </li>
          ))}
          </ul>
        </>
      )}
    </section>
  );
}
