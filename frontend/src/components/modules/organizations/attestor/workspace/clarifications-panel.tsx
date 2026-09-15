"use client";

import React, { useEffect, useState } from "react";
import {
  listAttestationClarifications,
  createAttestationClarification,
  markClarificationsSeen
} from "@/lib/generated/sdk.gen";
import type { ClarificationResponse } from "@/lib/generated/types.gen";
import { getAccessTokenHeaders, describeGeneratedError } from "@/lib/auth/form-client";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Spinner } from "@/components/ui/spinner";
import { Badge } from "@/components/ui/badge";

export interface ClarificationsPanelProps {
  attestationId: string;
  canWrite: boolean;
  /** Why the reviewer can no longer ask, shown in place of the Ask button. */
  lockedReason?: string;
}

export function ClarificationsPanel({
  attestationId,
  canWrite,
  lockedReason,
}: ClarificationsPanelProps) {
  const [clarifications, setClarifications] = useState<ClarificationResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [isAsking, setIsAsking] = useState(false);
  const [question, setQuestion] = useState("");
  const [submitting, setSubmitting] = useState(false);
  // Inline error for the ask-question action, shown without hiding the thread.
  const [actionError, setActionError] = useState<string | null>(null);

  const fetchClarifications = async () => {
    try {
      const res = await listAttestationClarifications({
        path: { attestation_id: attestationId },
        headers: getAccessTokenHeaders()
      });
      if (res.error) throw new Error(describeGeneratedError(res.error));
      setClarifications(res.data);
      // The reviewer opening this panel has now seen any answered
      // clarifications, so clear the queue's "answer received" dot. Idempotent
      // server-side (only stamps unseen answers); fire-and-forget.
      if (canWrite && res.data.some((clar: ClarificationResponse) => clar.status === "answered")) {
        void markClarificationsSeen({
          path: { attestation_id: attestationId },
          headers: getAccessTokenHeaders()
        });
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load clarifications.");
    } finally {
      setLoading(false);
    }
  };

    useEffect(() => {
    fetchClarifications();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [attestationId]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!question) return;

    setSubmitting(true);
    setActionError(null);
    try {
      const res = await createAttestationClarification({
        path: { attestation_id: attestationId },
        body: { question },
        headers: getAccessTokenHeaders()
      });
      if (res.error) throw new Error(describeGeneratedError(res.error));

      await fetchClarifications();
      setQuestion("");
      setIsAsking(false);
    } catch (err: unknown) {
      setActionError(err instanceof Error ? err.message : "Failed to ask clarification.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="space-y-8">
      <div className="flex items-center justify-between border-b border-border-default pb-4">
        <div>
          <h2 className="text-xl font-semibold text-foreground">
            Clarifications
          </h2>
          <p className="mt-1 text-sm text-foreground-muted">
            {lockedReason ?? "Ask the requestor for additional details or clarification."}
          </p>
        </div>
        {canWrite && !isAsking && (
          <Button onClick={() => setIsAsking(true)}>
            Ask Question
          </Button>
        )}
      </div>

      {loading ? (
        <div className="flex justify-center p-8"><Spinner className="h-6 w-6 text-accent" /></div>
      ) : error ? (
        <div className="p-4 text-sm text-error bg-error/5 rounded-xl border border-error/50">
          {error}
        </div>
      ) : (
        <div className="space-y-6">
          {actionError && (
            <div className="p-4 text-sm text-error bg-error/5 rounded-xl border border-error/50">
              {actionError}
            </div>
          )}
          {isAsking && canWrite && (
            <div className="rounded-xl border border-border-default bg-surface-elevated p-6">
              <h3 className="text-sm font-semibold mb-4 text-foreground">New Clarification</h3>
              <form onSubmit={handleSubmit} className="space-y-4">
                <div>
                  <label className="block text-sm font-medium text-foreground mb-1">Question <span className="text-error">*</span></label>
                  <Textarea 
                    placeholder="Describe what you need clarified..." 
                    value={question} 
                    onChange={(e) => setQuestion(e.target.value)}
                    required
                    className="min-h-[100px]"
                  />
                </div>

                <div className="flex justify-end gap-3 pt-2">
                  <Button type="button" variant="secondary" onClick={() => setIsAsking(false)}>
                    Cancel
                  </Button>
                  <Button type="submit" disabled={submitting || !question}>
                    {submitting ? "Sending..." : "Send Question"}
                  </Button>
                </div>
              </form>
            </div>
          )}

          {clarifications.length === 0 && !isAsking ? (
            <div className="rounded-xl border border-dashed border-border-default p-8 text-center text-foreground-muted text-sm">
              No clarifications asked yet.
            </div>
          ) : (
            <div className="space-y-4">
              {clarifications.map((clar) => (
                <div key={clar.id} className="rounded-xl border border-border-default bg-background p-6">
                  <div className="flex items-center justify-between mb-4">
                    <Badge variant="default" className="uppercase text-xs">{clar.status || "open"}</Badge>
                    <span className="text-xs text-foreground-muted">
                      Sent: {new Date(clar.sent_at).toLocaleDateString()}
                    </span>
                  </div>
                  
                  <div className="mb-4">
                    <p className="text-sm font-medium text-foreground mb-1">Question:</p>
                    <p className="text-sm text-foreground-muted whitespace-pre-wrap">{clar.question}</p>
                  </div>

                  {clar.response ? (
                    <div className="border-t border-border-default pt-4 mt-4">
                      <div className="flex items-center justify-between mb-1">
                        <p className="text-sm font-medium text-foreground">Response:</p>
                        {clar.responded_at && (
                          <span className="text-xs text-foreground-muted">
                            {new Date(clar.responded_at).toLocaleDateString()}
                          </span>
                        )}
                      </div>
                      <p className="text-sm text-foreground whitespace-pre-wrap">{clar.response}</p>
                    </div>
                  ) : (
                    <div className="border-t border-border-default pt-4 mt-4 text-sm text-foreground-muted italic">
                      Waiting for requestor to respond...
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
