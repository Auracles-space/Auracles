"use client";

/**
 * Browser session management panel.
 *
 * Lists active refresh-token sessions and allows revocation through the
 * generated settings client. Access tokens remain in memory and are only sent
 * as bearer headers for protected API calls.
 */
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import {
  listSessions,
  revokeOtherSessions,
  revokeSession,
} from "@/lib/generated/sdk.gen";
import type { SessionResponse } from "@/lib/generated/types.gen";

import { FormMessage } from "../auth/form-message";

type SessionListProps = {
  autoload?: boolean;
  initialSessions?: SessionResponse[];
};

/**
 * Render active sessions and controls to revoke them.
 *
 * @param props - Optional initial sessions and autoload behavior.
 */
export function SessionList({
  autoload = false,
  initialSessions = [],
}: SessionListProps) {
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [sessions, setSessions] = useState<SessionResponse[]>(initialSessions);
  const [success, setSuccess] = useState<string | null>(null);

  async function loadActiveSessions(): Promise<void> {
    setError(null);
    setIsLoading(true);
    configureBrowserClient();
    const result = await listSessions({ headers: getAccessTokenHeaders() });
    setIsLoading(false);

    if (!result.response.ok || !result.data) {
      setError(describeGeneratedError(result.error));
      return;
    }

    setSessions(result.data.sessions);
  }

  async function revoke(sessionId: string): Promise<void> {
    setError(null);
    setSuccess(null);
    configureBrowserClient();
    const result = await revokeSession({
      headers: getAccessTokenHeaders(),
      path: { session_id: sessionId },
    });

    if (!result.response.ok) {
      setError(describeGeneratedError(result.error));
      return;
    }

    setSessions((current) => current.filter((session) => session.id !== sessionId));
    setSuccess(result.data?.message ?? "Session revoked.");
  }

  async function revokeOthers(): Promise<void> {
    setError(null);
    setSuccess(null);
    configureBrowserClient();
    const result = await revokeOtherSessions({ headers: getAccessTokenHeaders() });

    if (!result.response.ok) {
      setError(describeGeneratedError(result.error));
      return;
    }

    setSessions((current) => current.filter((session) => session.current));
    setSuccess(result.data?.message ?? "Other sessions revoked.");
  }

  useEffect(() => {
    if (autoload) {
      void loadActiveSessions();
    }
  }, [autoload]);

  return (
    <div className="space-y-5">
      <div>
        <h2 className="font-heading text-xl font-semibold text-foreground">
          Browser sessions
        </h2>
        <p className="mt-2 text-sm leading-6 text-foreground-muted">
          Review active refresh-token sessions and revoke access you no longer
          recognize.
        </p>
      </div>

      {error ? <FormMessage kind="error" message={error} /> : null}
      {success ? <FormMessage kind="success" message={success} /> : null}

      <div className="flex flex-col gap-3 sm:flex-row">
        <Button disabled={isLoading} onClick={loadActiveSessions} variant="secondary" className="flex items-center gap-2">
          <svg className="h-4 w-4 text-foreground-muted" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 1121.21 7.89" />
          </svg>
          {isLoading ? "Loading sessions" : "Refresh sessions"}
        </Button>
        <Button onClick={revokeOthers} variant="secondary" className="flex items-center gap-2">
          <svg className="h-4 w-4 text-foreground-muted" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
          </svg>
          Revoke other sessions
        </Button>
      </div>

      <div className="space-y-3">
        {sessions.length === 0 ? (
          <p className="rounded-[20px] border border-border-strong bg-surface-2 p-4 text-sm text-foreground-muted shadow-sm">
            No active sessions are loaded.
          </p>
        ) : (
          sessions.map((session) => (
            <article
              className="rounded-[20px] border border-border-strong bg-surface-2 p-4 shadow-sm"
              key={session.id}
            >
              <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <div className="font-heading text-sm font-semibold text-foreground">
                    {session.current ? "Current session" : "Browser session"}
                  </div>
                  <p className="mt-2 text-xs leading-5 text-foreground-muted">
                    {session.user_agent ?? "Unknown browser"} ·{" "}
                    {session.ip ?? "Unknown IP"}
                  </p>
                  <p className="mt-1 text-xs leading-5 text-foreground-subtle">
                    Last seen {new Date(session.last_seen).toLocaleString()}
                  </p>
                </div>
                <button
                  aria-label="Revoke session"
                  onClick={() => void revoke(session.id)}
                  type="button"
                  className={[
                    "flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border transition-all cursor-pointer",
                    session.current
                      ? "border-error/40 bg-error/5 text-error hover:bg-error/10 focus-visible:ring-2 focus-visible:ring-error"
                      : "border-border-default bg-surface-1 text-foreground-muted hover:border-error/30 hover:bg-error/5 hover:text-error focus-visible:ring-2 focus-visible:ring-accent"
                  ].join(" ")}
                >
                  <svg className="h-4.5 w-4.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                  </svg>
                </button>
              </div>
            </article>
          ))
        )}
      </div>
    </div>
  );
}
