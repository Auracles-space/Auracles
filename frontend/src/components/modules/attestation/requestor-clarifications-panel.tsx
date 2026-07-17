"use client";

/**
 * Requestor-side clarifications panel.
 *
 * Lists the clarification questions an attestor has raised on this attestation
 * and lets the requestor (the framework owner who requested it) answer any that
 * are still open. Answered and expired questions render read-only.
 */
import { useEffect, useState } from "react";

import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import {
  listAttestationClarifications,
  respondAttestationClarification,
} from "@/lib/generated/sdk.gen";
import type { ClarificationResponse } from "@/lib/generated/types.gen";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Spinner } from "@/components/ui/spinner";
import { Badge } from "@/components/ui/badge";

type RequestorClarificationsPanelProps = {
  /** Attestation whose clarifications are shown. */
  attestationId: string;
};

/** Format an ISO timestamp for display, or a dash when absent. */
function formatWhen(value: string | null | undefined): string {
  return value ? new Date(value).toLocaleString() : "—";
}

/**
 * Render the requestor's clarification thread with answer boxes on open items.
 *
 * @param props - The attestation id to load clarifications for.
 */
export function RequestorClarificationsPanel({
  attestationId,
}: RequestorClarificationsPanelProps) {
  const [items, setItems] = useState<ClarificationResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [submittingId, setSubmittingId] = useState<string | null>(null);

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [attestationId]);

  /** Load the clarification thread for this attestation. */
  async function load() {
    configureBrowserClient();
    const result = await listAttestationClarifications({
      headers: getAccessTokenHeaders(),
      path: { attestation_id: attestationId },
    });
    setLoading(false);
    if (!result.response.ok || !result.data) {
      setError(describeGeneratedError(result.error));
      return;
    }
    setError(null);
    setItems(result.data);
  }

  /** Submit the requestor's answer to one open clarification. */
  async function handleRespond(clarificationId: string) {
    const response = (answers[clarificationId] ?? "").trim();
    if (!response) return;
    setSubmittingId(clarificationId);
    setError(null);
    configureBrowserClient();
    const result = await respondAttestationClarification({
      body: { response },
      headers: getAccessTokenHeaders(),
      path: {
        attestation_id: attestationId,
        clarification_id: clarificationId,
      },
    });
    setSubmittingId(null);
    if (!result.response.ok) {
      setError(describeGeneratedError(result.error));
      return;
    }
    setAnswers((current) => {
      const next = { ...current };
      delete next[clarificationId];
      return next;
    });
    await load();
  }

  if (loading) {
    return (
      <div className="flex items-center gap-2 rounded-2xl border border-border-default bg-surface-1 p-6 text-sm text-foreground-muted shadow-sm">
        <Spinner className="h-4 w-4" /> Loading clarifications…
      </div>
    );
  }

  // Nothing to show and no error: the attestor has not asked anything yet. Keep
  // the panel out of the way rather than rendering an empty card.
  if (items.length === 0 && !error) {
    return null;
  }

  return (
    <div className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
      <h2 className="font-heading text-xl font-bold text-foreground">
        Clarifications
      </h2>
      <p className="mt-1 text-sm text-foreground-muted">
        The attestor may ask for more detail here. Answering an open question
        sends it straight back to them.
      </p>

      {error ? (
        <p className="mt-4 rounded-xl border border-error/30 bg-error/10 p-3 text-sm text-error">
          {error}
        </p>
      ) : null}

      <div className="mt-4 grid gap-4">
        {items.map((item) => {
          const isOpen = item.status === "open";
          return (
            <div
              className="rounded-xl border border-border-default bg-surface-2 p-4"
              key={item.id}
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-xs text-foreground-muted">
                  Asked {formatWhen(item.sent_at)}
                </span>
                <Badge variant={isOpen ? "warning" : "default"}>
                  {item.status}
                </Badge>
              </div>
              <p className="mt-2 text-sm font-semibold text-foreground">
                {item.question}
              </p>

              {isOpen ? (
                <div className="mt-3 grid gap-2">
                  <p className="text-xs text-foreground-muted">
                    Respond by {formatWhen(item.response_due_at)}
                  </p>
                  <Textarea
                    onChange={(event) =>
                      setAnswers((current) => ({
                        ...current,
                        [item.id]: event.target.value,
                      }))
                    }
                    placeholder="Type your answer for the attestor…"
                    value={answers[item.id] ?? ""}
                  />
                  <div>
                    <Button
                      disabled={
                        submittingId === item.id ||
                        (answers[item.id] ?? "").trim().length === 0
                      }
                      loading={submittingId === item.id}
                      onClick={() => handleRespond(item.id)}
                    >
                      Send answer
                    </Button>
                  </div>
                </div>
              ) : (
                <div className="mt-2">
                  <p className="text-xs font-semibold text-foreground-muted">
                    Your answer
                  </p>
                  <p className="mt-1 text-sm text-foreground-muted">
                    {item.response ?? "—"}
                  </p>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
