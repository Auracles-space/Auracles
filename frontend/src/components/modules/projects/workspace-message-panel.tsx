"use client";

/**
 * Workspace conversation panel.
 *
 * Renders the Operator/Contributor message timeline as a two-party chat: own
 * messages right-aligned, the other party left-aligned with name and time, and
 * project system events (funded, submitted, approved, ...) as centered timeline
 * markers rather than speech bubbles — because they are facts, not messages.
 *
 * Maps to: FR-PROJ-005.
 */
import { useEffect, useMemo, useRef, useState } from "react";

import type { WorkspaceMessageResponse } from "@/lib/generated/types.gen";

const SYSTEM_EVENT_LABELS: Record<string, string> = {
  amendment_accepted: "Amendment accepted",
  amendment_expired: "Amendment expired",
  amendment_proposed: "Amendment proposed",
  amendment_rejected: "Amendment rejected",
  deliverable_approved: "Deliverable approved",
  deliverable_auto_approved: "Deliverable auto-approved",
  deliverable_revision_requested: "Revision requested",
  deliverable_submitted: "Deliverable submitted",
  dispute_raised: "Dispute raised",
  dispute_resolved: "Dispute resolved",
  milestone_funded: "Milestone funded",
  milestone_plan_reopened: "Milestone plan reopened",
};

/** Format an ISO timestamp as a compact, locale-aware time. */
function formatTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

/** Human label for a system event, falling back to a de-snaked form. */
function systemLabel(event: string): string {
  return SYSTEM_EVENT_LABELS[event] ?? event.replaceAll("_", " ");
}

type WorkspaceMessagePanelProps = {
  messages: WorkspaceMessageResponse[];
  currentUserId: string | null;
  connected: boolean;
  onSend: (body: string) => Promise<boolean>;
};

/**
 * Render the workspace chat timeline plus composer.
 */
export function WorkspaceMessagePanel({
  messages,
  currentUserId,
  connected,
  onSend,
}: WorkspaceMessagePanelProps) {
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const endRef = useRef<HTMLDivElement | null>(null);

  // Chat reads oldest -> newest regardless of how items were inserted.
  const ordered = useMemo(
    () =>
      [...messages].sort(
        (a, b) =>
          new Date(a.created_at).getTime() - new Date(b.created_at).getTime(),
      ),
    [messages],
  );

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [ordered.length]);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (draft.trim().length === 0) {
      return;
    }
    setSending(true);
    const ok = await onSend(draft.trim());
    setSending(false);
    if (ok) {
      setDraft("");
    }
  }

  return (
    <section className="grid gap-4 rounded-2xl border border-border-default bg-surface-1 p-4 shadow-sm sm:p-6">
      <div className="flex items-center justify-between">
        <h2 className="font-heading text-xl font-semibold text-foreground">
          Messages
        </h2>
        <span className="text-xs text-foreground-subtle">
          {connected ? "Live" : "Offline"}
        </span>
      </div>

      <div className="grid max-h-[28rem] gap-3 overflow-y-auto pr-1">
        {ordered.length === 0 ? (
          <p className="py-8 text-center text-sm text-foreground-muted">
            No messages yet. Say hello to get the work started.
          </p>
        ) : null}
        {ordered.map((message) => {
          if (message.system_event) {
            return (
              <div
                className="flex items-center gap-3 py-1 text-xs text-foreground-subtle"
                key={message.id}
              >
                <span className="h-px flex-1 bg-border-default" />
                <span className="uppercase tracking-[0.05em]">
                  {systemLabel(message.system_event)}
                </span>
                <span className="h-px flex-1 bg-border-default" />
              </div>
            );
          }
          const mine = message.sender_id === currentUserId;
          return (
            <div
              className={mine ? "flex justify-end" : "flex justify-start"}
              key={message.id}
            >
              <div
                className={[
                  "max-w-[80%] rounded-2xl px-4 py-2.5 text-sm",
                  mine
                    ? "bg-accent text-white"
                    : "bg-surface-2 text-foreground",
                ].join(" ")}
              >
                {!mine ? (
                  <p className="mb-0.5 text-xs font-semibold text-foreground-muted">
                    {message.sender_name ?? "Member"}
                  </p>
                ) : null}
                <p className="whitespace-pre-wrap leading-6">{message.body}</p>
                {message.file_keys && message.file_keys.length > 0 ? (
                  <p
                    className={[
                      "mt-1 text-xs",
                      mine ? "text-white/80" : "text-foreground-subtle",
                    ].join(" ")}
                  >
                    {message.file_keys.length} attachment
                    {message.file_keys.length === 1 ? "" : "s"}
                  </p>
                ) : null}
                <p
                  className={[
                    "mt-1 text-[11px]",
                    mine ? "text-white/70" : "text-foreground-subtle",
                  ].join(" ")}
                >
                  {formatTime(message.created_at)}
                </p>
              </div>
            </div>
          );
        })}
        <div ref={endRef} />
      </div>

      <form className="flex flex-col gap-3 sm:flex-row" onSubmit={handleSubmit}>
        <input
          aria-label="Message"
          className="min-h-12 flex-1 rounded-xl border border-border-default bg-surface-2 px-4 text-sm outline-none transition-all focus:border-accent"
          onChange={(event) => setDraft(event.target.value)}
          placeholder="Write a message..."
          value={draft}
        />
        <button
          className="min-h-12 rounded-xl bg-foreground px-6 text-sm font-semibold text-background shadow-sm outline-none transition-all hover:bg-foreground/90 focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-60"
          disabled={sending || draft.trim().length === 0}
          type="submit"
        >
          {sending ? "Sending" : "Send"}
        </button>
      </form>
    </section>
  );
}
