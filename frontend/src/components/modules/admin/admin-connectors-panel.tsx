"use client";

/**
 * Admin connector oversight panel.
 *
 * Read-only: administrators audit user OAuth connections to external file
 * providers (Google Drive), filtering by status to spot revoked or
 * reauth-required connections. Encrypted tokens are never returned by the API.
 * Renders as a table on desktop and stacked cards on mobile.
 *
 * Maps to: admin external-connection oversight.
 */
import { useEffect, useState } from "react";

import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import { listAdminConnectorsV1AdminConnectorsGet } from "@/lib/generated/sdk.gen";
import { TableSkeleton } from "@/components/ui/skeletons/table-skeleton";
import type {
  AdminConnectorItem,
  AdminConnectorsResponse,
} from "@/lib/generated/types.gen";

type ConnectorStatusFilter = "all" | "active" | "revoked" | "reauth_required";

/** Status pill styles keyed by connection status. */
const STATUS_STYLES: Record<string, string> = {
  active: "border-success/30 bg-success/10 text-success",
  reauth_required: "border-warning/30 bg-warning/10 text-warning",
  revoked: "border-error/30 bg-error/10 text-error",
};

/**
 * Format a connector timestamp for compact admin copy.
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
 * Render the read-only admin external-connection directory.
 */
export function AdminConnectorsPanel() {
  const [directory, setDirectory] = useState<AdminConnectorsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState<ConnectorStatusFilter>("all");

  useEffect(() => {
    let mounted = true;

    async function loadConnectors(): Promise<void> {
      configureBrowserClient();
      const result = await listAdminConnectorsV1AdminConnectorsGet({
        headers: getAccessTokenHeaders(),
        query: { page: 1, page_size: 20, status: statusFilter },
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
      setDirectory(result.data);
    }

    void loadConnectors();
    return () => {
      mounted = false;
    };
  }, [statusFilter]);

  if (loading) {
    return <TableSkeleton />;
  }

  const items: AdminConnectorItem[] = directory?.items ?? [];

  return (
    <section className="grid gap-6">
      <header className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
        <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
          Admin connectors
        </p>
        <h2 className="mt-2 font-heading text-3xl font-bold text-foreground">
          External connections
        </h2>
        <p className="mt-3 max-w-3xl text-sm leading-6 text-foreground-muted">
          Audit user OAuth connections to external file providers. Read-only —
          filter by status to find revoked or reauth-required connections.
          Stored tokens are never shown.
        </p>
      </header>

      <section className="grid gap-4 rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm md:max-w-xs">
        <label className="grid gap-2 text-sm font-semibold text-foreground">
          Status
          <select
            className="min-h-12 rounded-xl border border-border-default bg-background px-4 text-sm text-foreground outline-none transition-colors focus-visible:ring-2 focus-visible:ring-accent"
            onChange={(event) =>
              setStatusFilter(event.target.value as ConnectorStatusFilter)
            }
            value={statusFilter}
          >
            <option value="all">All statuses</option>
            <option value="active">Active</option>
            <option value="reauth_required">Reauth required</option>
            <option value="revoked">Revoked</option>
          </select>
        </label>
      </section>

      {error ? (
        <div className="rounded-2xl border border-error/30 bg-error/10 p-4 text-sm text-error">
          {error}
        </div>
      ) : null}

      {items.length === 0 ? (
        <div className="rounded-2xl border border-border-default bg-surface-1 p-8 text-center text-sm text-foreground-muted shadow-sm">
          No connections match this filter.
        </div>
      ) : (
        <div className="grid gap-4 md:gap-0 md:divide-y md:divide-border-default/40 md:rounded-2xl md:border md:border-border-default md:bg-surface-1 md:shadow-sm overflow-hidden">
          <div className="hidden md:grid md:grid-cols-[1.4fr_1fr_0.9fr_1.1fr_1.1fr] md:gap-4 md:bg-surface-2/40 md:p-4 md:pl-6 md:pr-6 text-xs font-semibold uppercase tracking-wider text-foreground-muted select-none">
            <div>Connected account</div>
            <div>Provider</div>
            <div>Status</div>
            <div>Token expires</div>
            <div className="text-right">Updated</div>
          </div>

          {items.map((item) => (
            <article
              className="
                flex flex-col gap-3 rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm
                md:grid md:grid-cols-[1.4fr_1fr_0.9fr_1.1fr_1.1fr] md:items-center md:gap-4
                md:rounded-none md:border-none md:bg-transparent md:p-4 md:pl-6 md:pr-6 md:shadow-none
                md:hover:bg-surface-2/30 transition-colors
              "
              key={item.connection_id}
              role="article"
            >
              <div className="grid gap-0.5">
                <p className="text-sm font-semibold text-foreground md:text-xs">
                  {item.provider_account_email ?? "—"}
                </p>
                <p className="font-mono text-[11px] text-foreground-subtle break-all">
                  user: {item.user_id}
                </p>
              </div>

              <div>
                <span className="md:hidden text-xs text-foreground-muted block mb-1 font-semibold uppercase tracking-wider">
                  Provider
                </span>
                <span className="inline-flex items-center rounded-md border border-border-default bg-surface-2 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-foreground-muted">
                  {item.provider}
                </span>
              </div>

              <div>
                <span className="md:hidden text-xs text-foreground-muted block mb-1 font-semibold uppercase tracking-wider">
                  Status
                </span>
                <span
                  className={[
                    "inline-flex items-center rounded-badge border px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wider",
                    STATUS_STYLES[item.status] ??
                      "border-border-default bg-surface-2 text-foreground-muted",
                  ].join(" ")}
                >
                  {item.status}
                </span>
              </div>

              <div className="text-sm text-foreground md:text-xs">
                <span className="md:hidden text-xs text-foreground-muted block mb-1 font-semibold uppercase tracking-wider">
                  Token expires
                </span>
                {formatTimestamp(item.token_expires_at)}
              </div>

              <div className="text-sm text-foreground md:text-right md:text-xs">
                <span className="md:hidden text-xs text-foreground-muted block mb-1 font-semibold uppercase tracking-wider">
                  Updated
                </span>
                {formatTimestamp(item.updated_at)}
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
