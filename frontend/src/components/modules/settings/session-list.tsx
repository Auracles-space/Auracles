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
        <Button disabled={isLoading} onClick={loadActiveSessions} variant="secondary">
          {isLoading ? "Loading sessions" : "Refresh sessions"}
        </Button>
        <Button onClick={revokeOthers} variant="secondary">
          Revoke other sessions
        </Button>
      </div>

      <div className="space-y-3">
        {sessions.length === 0 ? (
          <p className="rounded-card border border-border-strong bg-surface-3 p-4 text-sm text-foreground-muted">
            No active sessions are loaded.
          </p>
        ) : (
          sessions.map((session) => (
            <article
              className="rounded-card border border-border-strong bg-surface-3 p-4"
              key={session.id}
            >
              <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
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
                <Button
                  onClick={() => void revoke(session.id)}
                  variant={session.current ? "destructive" : "secondary"}
                >
                  Revoke session
                </Button>
              </div>
            </article>
          ))
        )}
      </div>
    </div>
  );
}
