"use client";

/**
 * Admin GDPR request oversight panel.
 *
 * Read-only compliance queues: administrators monitor account-deletion and
 * data-export requests to ensure they progress and to see when a deletion is
 * blocked by open obligations. No destructive actions here — the internal
 * export bundle key is never returned. Each queue renders as a table on
 * desktop and stacked cards on mobile.
 *
 * Maps to: admin GDPR oversight (deletion + export request queues).
 */
import { useEffect, useState } from "react";

import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import {
  listAdminDeletionRequestsV1AdminGdprDeletionRequestsGet,
  listAdminExportRequestsV1AdminGdprExportRequestsGet,
} from "@/lib/generated/sdk.gen";
import { TableSkeleton } from "@/components/ui/skeletons/table-skeleton";
import type {
  AdminDeletionRequestItem,
  AdminExportRequestItem,
} from "@/lib/generated/types.gen";

/** Status pill styles shared across GDPR request statuses. */
const STATUS_STYLES: Record<string, string> = {
  pending: "border-border-default bg-surface-2 text-foreground-muted",
  processing: "border-warning/30 bg-warning/10 text-warning",
  scheduled: "border-warning/30 bg-warning/10 text-warning",
  ready: "border-success/30 bg-success/10 text-success",
  completed: "border-success/30 bg-success/10 text-success",
  blocked: "border-error/30 bg-error/10 text-error",
  failed: "border-error/30 bg-error/10 text-error",
  cancelled: "border-border-default bg-surface-2 text-foreground-subtle",
  expired: "border-border-default bg-surface-2 text-foreground-subtle",
};

/**
 * Format a GDPR timestamp for compact admin copy.
 *
 * @param value - ISO timestamp string, or null.
 */
function formatTimestamp(value: string | null): string {
  if (!value) {
    return "—";
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
 * Render a status pill for one GDPR request.
 *
 * @param status - Request status string.
 */
function StatusPill({ status }: { status: string }) {
  return (
    <span
      className={[
        "inline-flex items-center rounded-badge border px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wider",
        STATUS_STYLES[status] ?? "border-border-default bg-surface-2 text-foreground-muted",
      ].join(" ")}
    >
      {status}
    </span>
  );
}

/**
 * Render the read-only admin GDPR request queues.
 */
export function AdminGdprPanel() {
  const [deletions, setDeletions] = useState<AdminDeletionRequestItem[]>([]);
  const [exports, setExports] = useState<AdminExportRequestItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;

    async function load(): Promise<void> {
      configureBrowserClient();
      const headers = getAccessTokenHeaders();
      const [deletionResult, exportResult] = await Promise.all([
        listAdminDeletionRequestsV1AdminGdprDeletionRequestsGet({
          headers,
          query: { page: 1, page_size: 20, status: "all" },
        }),
        listAdminExportRequestsV1AdminGdprExportRequestsGet({
          headers,
          query: { page: 1, page_size: 20, status: "all" },
        }),
      ]);

      if (!mounted) {
        return;
      }
      setLoading(false);

      if (!deletionResult.response.ok || !deletionResult.data) {
        setError(describeGeneratedError(deletionResult.error));
        return;
      }
      if (!exportResult.response.ok || !exportResult.data) {
        setError(describeGeneratedError(exportResult.error));
        return;
      }
      setError(null);
      setDeletions(deletionResult.data.items);
      setExports(exportResult.data.items);
    }

    void load();
    return () => {
      mounted = false;
    };
  }, []);

  if (loading) {
    return <TableSkeleton />;
  }

  return (
    <section className="grid gap-6">
      <header className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
        <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
          Admin GDPR
        </p>
        <h2 className="mt-2 font-heading text-3xl font-bold text-foreground">
          Data requests
        </h2>
        <p className="mt-3 max-w-3xl text-sm leading-6 text-foreground-muted">
          Monitor account-deletion and data-export requests. Read-only — see
          when a deletion is blocked by open obligations. Personal export files
          are never shown.
        </p>
      </header>

      {error ? (
        <div className="rounded-2xl border border-error/30 bg-error/10 p-4 text-sm text-error">
          {error}
        </div>
      ) : null}

      {/* Account deletion requests */}
      <section className="grid gap-4">
        <h3 className="font-heading text-lg font-bold text-foreground">
          Account deletions
        </h3>
        {deletions.length === 0 ? (
          <p className="rounded-2xl border border-border-default bg-surface-1 p-6 text-center text-sm text-foreground-muted shadow-sm">
            No account-deletion requests.
          </p>
        ) : (
          <div className="grid gap-4 md:gap-0 md:divide-y md:divide-border-default/40 md:rounded-2xl md:border md:border-border-default md:bg-surface-1 md:shadow-sm overflow-hidden">
            <div className="hidden md:grid md:grid-cols-[1.5fr_0.9fr_1.5fr_1.1fr_1.1fr] md:gap-4 md:bg-surface-2/40 md:p-4 md:pl-6 md:pr-6 text-xs font-semibold uppercase tracking-wider text-foreground-muted select-none">
              <div>User</div>
              <div>Status</div>
              <div>Blockers</div>
              <div>Scheduled</div>
              <div className="text-right">Requested</div>
            </div>
            {deletions.map((item) => (
              <article
                className="
                  flex flex-col gap-3 rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm
                  md:grid md:grid-cols-[1.5fr_0.9fr_1.5fr_1.1fr_1.1fr] md:items-center md:gap-4
                  md:rounded-none md:border-none md:bg-transparent md:p-4 md:pl-6 md:pr-6 md:shadow-none
                  md:hover:bg-surface-2/30 transition-colors
                "
                key={item.request_id}
                role="article"
              >
                <p className="font-mono text-xs text-foreground-muted break-all">
                  {item.user_id}
                </p>
                <div>
                  <span className="md:hidden text-xs text-foreground-muted block mb-1 font-semibold uppercase tracking-wider">
                    Status
                  </span>
                  <StatusPill status={item.status} />
                </div>
                <div className="flex flex-wrap gap-1">
                  {item.blocked_reasons.length === 0 ? (
                    <span className="text-xs text-foreground-subtle">None</span>
                  ) : (
                    item.blocked_reasons.map((reason, index) => (
                      <span
                        className="inline-flex items-center rounded-md border border-error/30 bg-error/10 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-error"
                        key={`${item.request_id}:${index}`}
                      >
                        {String(reason.code ?? "blocked")}
                      </span>
                    ))
                  )}
                </div>
                <div className="text-sm text-foreground md:text-xs">
                  <span className="md:hidden text-xs text-foreground-muted block mb-1 font-semibold uppercase tracking-wider">
                    Scheduled
                  </span>
                  {formatTimestamp(item.scheduled_for)}
                </div>
                <div className="text-sm text-foreground md:text-right md:text-xs">
                  <span className="md:hidden text-xs text-foreground-muted block mb-1 font-semibold uppercase tracking-wider">
                    Requested
                  </span>
                  {formatTimestamp(item.requested_at)}
                </div>
              </article>
            ))}
          </div>
        )}
      </section>

      {/* Data export requests */}
      <section className="grid gap-4">
        <h3 className="font-heading text-lg font-bold text-foreground">
          Data exports
        </h3>
        {exports.length === 0 ? (
          <p className="rounded-2xl border border-border-default bg-surface-1 p-6 text-center text-sm text-foreground-muted shadow-sm">
            No data-export requests.
          </p>
        ) : (
          <div className="grid gap-4 md:gap-0 md:divide-y md:divide-border-default/40 md:rounded-2xl md:border md:border-border-default md:bg-surface-1 md:shadow-sm overflow-hidden">
            <div className="hidden md:grid md:grid-cols-[1.6fr_0.9fr_1.4fr_1.1fr] md:gap-4 md:bg-surface-2/40 md:p-4 md:pl-6 md:pr-6 text-xs font-semibold uppercase tracking-wider text-foreground-muted select-none">
              <div>User</div>
              <div>Status</div>
              <div>Failure</div>
              <div className="text-right">Requested</div>
            </div>
            {exports.map((item) => (
              <article
                className="
                  flex flex-col gap-3 rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm
                  md:grid md:grid-cols-[1.6fr_0.9fr_1.4fr_1.1fr] md:items-center md:gap-4
                  md:rounded-none md:border-none md:bg-transparent md:p-4 md:pl-6 md:pr-6 md:shadow-none
                  md:hover:bg-surface-2/30 transition-colors
                "
                key={item.request_id}
                role="article"
              >
                <p className="font-mono text-xs text-foreground-muted break-all">
                  {item.user_id}
                </p>
                <div>
                  <span className="md:hidden text-xs text-foreground-muted block mb-1 font-semibold uppercase tracking-wider">
                    Status
                  </span>
                  <StatusPill status={item.status} />
                </div>
                <div className="text-sm text-foreground-muted md:text-xs">
                  <span className="md:hidden text-xs text-foreground-muted block mb-1 font-semibold uppercase tracking-wider">
                    Failure
                  </span>
                  {item.failure_reason ?? "—"}
                </div>
                <div className="text-sm text-foreground md:text-right md:text-xs">
                  <span className="md:hidden text-xs text-foreground-muted block mb-1 font-semibold uppercase tracking-wider">
                    Requested
                  </span>
                  {formatTimestamp(item.requested_at)}
                </div>
              </article>
            ))}
          </div>
        )}
      </section>
    </section>
  );
}
