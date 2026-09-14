"use client";

/**
 * Webhook delivery and audit log tabs of the admin money-movement panel.
 *
 * Webhook rows show stored processing errors; raw payloads are never returned
 * by the API. Audit rows show the action, target, and acting user.
 *
 * Maps to: admin financial oversight (money movement traceability).
 */
import type {
  AdminAuditLogsResponse,
  AdminWebhookEventsResponse,
} from "@/lib/generated/types.gen";

import {
  EmptyState,
  Pill,
  formatTimestamp,
  toneForStatus,
} from "./admin-money-primitives";

/**
 * Render the provider webhook delivery log, including stored errors.
 *
 * @param props.data - Webhook events response, or null before load.
 */
export function WebhooksView({ data }: { data: AdminWebhookEventsResponse | null }) {
  const items = data?.items ?? [];
  if (!items.length) {
    return <EmptyState message="No webhook deliveries match these filters." />;
  }

  return (
    <ul className="grid gap-4 md:gap-0 md:divide-y md:divide-border-default/40 md:overflow-hidden md:rounded-2xl md:border md:border-border-default md:bg-surface-1 md:shadow-sm">
      {items.map((event) => (
        <li
          className="grid gap-2 rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm md:grid-cols-[1.4fr_0.8fr_0.8fr_1.6fr] md:items-start md:gap-4 md:rounded-none md:border-none md:bg-transparent md:p-4 md:px-6 md:shadow-none"
          key={event.event_id}
        >
          <div className="grid gap-0.5">
            <span className="text-sm font-semibold text-foreground">
              {event.event_type}
            </span>
            <span className="break-all font-mono text-[11px] text-foreground-subtle">
              {event.provider_event_id}
            </span>
          </div>
          <Pill>{event.provider}</Pill>
          <Pill tone={toneForStatus(event.status)}>{event.status}</Pill>
          <div className="grid gap-1 text-xs md:text-right">
            {event.error ? (
              <span className="break-words font-medium text-error">
                {event.error}
              </span>
            ) : null}
            <span className="text-foreground-subtle">
              {formatTimestamp(event.received_at)}
            </span>
          </div>
        </li>
      ))}
    </ul>
  );
}

/**
 * Render the filtered audit log view.
 *
 * @param props.data - Audit log response, or null before load.
 */
export function AuditView({ data }: { data: AdminAuditLogsResponse | null }) {
  const items = data?.items ?? [];
  if (!items.length) {
    return <EmptyState message="No audit entries match these filters." />;
  }

  return (
    <ul className="grid gap-4 md:gap-0 md:divide-y md:divide-border-default/40 md:overflow-hidden md:rounded-2xl md:border md:border-border-default md:bg-surface-1 md:shadow-sm">
      {items.map((log) => (
        <li
          className="grid gap-2 rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm md:grid-cols-[1.2fr_1fr_1.4fr] md:items-center md:gap-4 md:rounded-none md:border-none md:bg-transparent md:p-4 md:px-6 md:shadow-none"
          key={log.log_id}
        >
          <span className="text-sm font-semibold text-foreground">{log.action}</span>
          <div className="grid gap-0.5">
            <Pill>{log.target_type}</Pill>
            {log.target_id ? (
              <span className="break-all font-mono text-[11px] text-foreground-subtle">
                {log.target_id}
              </span>
            ) : null}
          </div>
          <div className="grid gap-0.5 text-xs md:text-right">
            <span className="break-all font-mono text-foreground-muted">
              {log.actor_id ?? "system"}
            </span>
            <span className="text-foreground-subtle">
              {formatTimestamp(log.created_at)}
            </span>
          </div>
        </li>
      ))}
    </ul>
  );
}
