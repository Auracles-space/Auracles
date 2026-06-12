"use client";

/**
 * Consent settings panel.
 *
 * Shows current legal-document consent state, missing version acceptances, and
 * append-only history for the authenticated user.
 */
import { useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import {
  acceptCurrentConsentV1GdprConsentPost,
  listConsentHistoryV1GdprConsentGet,
} from "@/lib/generated/sdk.gen";
import type { ConsentHistoryResponse } from "@/lib/generated/types.gen";

import { FormMessage } from "../auth/form-message";

/**
 * Convert consent document keys into human-readable labels.
 *
 * @param value - Consent document enum value from the API.
 * @returns Human-readable label for settings UI.
 */
function formatDocumentLabel(value: string): string {
  switch (value) {
    case "terms_of_service":
      return "Terms of service";
    case "privacy_policy":
      return "Privacy policy";
    default:
      return value.replaceAll("_", " ");
  }
}

/**
 * Format a consent acceptance timestamp for concise history display.
 *
 * @param value - ISO timestamp from the API.
 * @returns Locale-aware short timestamp string.
 */
function formatAcceptedAt(value: string): string {
  const parsed = new Date(value);
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(parsed);
}

/**
 * Render current consent status and append-only history.
 */
export function ConsentSettingsPanel() {
  const [accepting, setAccepting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [history, setHistory] = useState<ConsentHistoryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;

    async function loadConsentHistory(): Promise<void> {
      configureBrowserClient();
      const result = await listConsentHistoryV1GdprConsentGet({
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
      setHistory(result.data);
    }

    void loadConsentHistory();
    return () => {
      mounted = false;
    };
  }, []);

  const missingDocuments = useMemo(
    () => history?.missing_documents ?? [],
    [history?.missing_documents],
  );

  async function submitCurrentConsent(): Promise<void> {
    setAccepting(true);
    setError(null);
    setMessage(null);
    configureBrowserClient();

    const result = await acceptCurrentConsentV1GdprConsentPost({
      body: {
        accept_privacy_policy: true,
        accept_terms: true,
      },
      headers: getAccessTokenHeaders(),
    });
    setAccepting(false);

    if (!result.response.ok || !result.data) {
      setError(describeGeneratedError(result.error));
      return;
    }

    setHistory(result.data);
    setMessage("You are up to date on legal consent.");
  }

  return (
    <section
      aria-labelledby="legal-consent-heading"
      className="space-y-6 rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm md:p-6"
      role="region"
    >
      <div>
        <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
          Legal settings
        </p>
        <h2
          className="mt-2 font-heading text-2xl font-bold text-foreground"
          id="legal-consent-heading"
        >
          Legal consent
        </h2>
        <p className="mt-3 max-w-2xl text-sm leading-6 text-foreground-muted">
          Review accepted legal versions and re-accept new Terms of Service or
          Privacy Policy revisions when required.
        </p>
      </div>

      {loading ? (
        <p className="rounded-xl border border-border-default bg-surface-2 px-3 py-2 text-sm text-foreground-muted">
          Loading consent history...
        </p>
      ) : null}

      {error ? <FormMessage kind="error" message={error} /> : null}
      {message ? <FormMessage kind="success" message={message} /> : null}

      {history ? (
        <>
          <div
            className={[
              "space-y-4 rounded-xl border p-4",
              missingDocuments.length > 0
                ? "border-warning/30 bg-warning/10"
                : "border-success/30 bg-success/10",
            ].join(" ")}
          >
            <div>
              <p
                className={[
                  "text-sm font-medium",
                  missingDocuments.length > 0 ? "text-warning" : "text-success",
                ].join(" ")}
              >
                {missingDocuments.length > 0
                  ? "New legal versions require your acceptance."
                  : "You are up to date on legal consent."}
              </p>
              <p className="mt-1 text-sm leading-6 text-foreground-muted">
                Current versions: Terms of Service{" "}
                {history.current_versions.terms_of_service}, Privacy Policy{" "}
                {history.current_versions.privacy_policy}.
              </p>
            </div>

            {missingDocuments.length > 0 ? (
              <>
                <ul className="space-y-2 text-sm text-foreground">
                  {missingDocuments.map((item) => (
                    <li key={item}>{formatDocumentLabel(item)}</li>
                  ))}
                </ul>
                <Button
                  disabled={accepting}
                  onClick={() => void submitCurrentConsent()}
                  type="button"
                >
                  {accepting ? "Saving..." : "Accept current versions"}
                </Button>
              </>
            ) : null}
          </div>

          <div className="space-y-3">
            <h3 className="font-heading text-lg font-semibold text-foreground">
              Consent history
            </h3>
            {history.items.length === 0 ? (
              <p className="rounded-xl border border-border-default bg-surface-2 px-3 py-2 text-sm text-foreground-muted">
                No consent history recorded yet.
              </p>
            ) : (
              <div className="grid gap-3">
                {history.items.map((item) => (
                  <article
                    className="rounded-xl border border-border-default bg-surface-2 p-4"
                    key={item.id}
                  >
                    <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                      <div>
                        <p className="text-sm font-medium text-foreground">
                          {formatDocumentLabel(item.document_type)}
                        </p>
                        <p className="mt-1 text-sm text-foreground-muted">
                          Version {item.version}
                        </p>
                      </div>
                      <p className="text-sm text-foreground-muted">
                        {formatAcceptedAt(item.accepted_at)}
                      </p>
                    </div>
                  </article>
                ))}
              </div>
            )}
          </div>
        </>
      ) : null}
    </section>
  );
}
