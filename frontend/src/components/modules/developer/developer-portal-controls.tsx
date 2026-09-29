"use client";

/**
 * Developer portal action controls.
 *
 * Contains the interactive Partner Developer forms for API keys, webhooks, and
 * payout requests so the main portal container stays focused on data loading.
 */
import type { FormEvent } from "react";
import { useId, useState } from "react";
import { createPortal } from "react-dom";

import type {
  ApiKeyResponse,
  PartnerWebhookResponse,
} from "@/lib/generated/types.gen";
import { allValid, isHttpUrl, isNonEmpty } from "@/lib/forms/validators";
import { formatLabel } from "@/lib/marketplace/format";

const webhookEvents = [
  "purchase.confirmed",
  "commission.cleared",
  "framework.updated",
];

/**
 * One-time secret reveal with a copy-to-clipboard control.
 *
 * Used for the raw API key and webhook signing secret, which the backend
 * returns exactly once — the user must copy them before navigating away.
 *
 * @param props.label - What the secret is, shown above the value.
 * @param props.value - The secret string to display and copy.
 */
function SecretReveal({ label, value }: { label: string; value: string }) {
  const [copied, setCopied] = useState(false);

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  }

  return (
    <div className="mt-4 rounded-xl border border-warning/30 bg-warning/10 p-3">
      <p className="text-xs font-semibold text-warning">{label}</p>
      <div className="mt-2 flex flex-col gap-2 sm:flex-row sm:items-center">
        <code className="min-w-0 flex-1 break-all font-mono text-sm text-foreground bg-surface-3 p-2 rounded-lg border border-border-default">
          {value}
        </code>
        <button
          className="min-h-12 sm:min-h-9 w-full sm:w-auto shrink-0 rounded-lg border border-warning/40 bg-surface-1 px-4 text-xs font-semibold text-foreground outline-none transition-colors hover:bg-surface-2 focus-visible:ring-2 focus-visible:ring-accent"
          onClick={() => void handleCopy()}
          type="button"
        >
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
    </div>
  );
}

/**
 * Full-screen modal revealing a freshly created key with a copy control.
 *
 * The backend returns the raw API key exactly once, so this blocks the rest of
 * the UI until the user confirms they have copied it — it can't be missed.
 *
 * @param props.value - The one-time key to reveal.
 * @param props.onDismiss - Called when the user confirms they have saved it.
 */
function OneTimeKeyModal({
  value,
  onDismiss,
}: {
  value: string;
  onDismiss: () => void;
}) {
  const [copied, setCopied] = useState(false);

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }

  if (typeof document === "undefined") {
    return null;
  }

  // Portal to <body> so the overlay escapes any ancestor stacking context
  // (transforms, backdrop-blur) that would otherwise trap it under the header.
  return createPortal(
    <div
      aria-modal="true"
      className="fixed inset-0 z-[100] grid place-items-center bg-black/50 p-4"
      role="dialog"
    >
      <div className="w-full max-w-lg rounded-2xl border border-border-default bg-surface-1 p-6 shadow-bento">
        <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
          New API key
        </p>
        <h3 className="mt-1 font-heading text-xl font-bold text-foreground">
          Copy your key now
        </h3>
        <p className="mt-2 text-sm text-foreground-muted">
          This is the only time the full key is shown. Store it somewhere safe —
          you can&apos;t see it again.
        </p>
        <div className="mt-4 flex items-center gap-2 rounded-xl border border-warning/30 bg-warning/10 p-3">
          <code className="min-w-0 flex-1 break-all font-mono text-sm text-foreground">
            {value}
          </code>
          <button
            className="min-h-10 shrink-0 rounded-lg bg-foreground px-3 text-xs font-semibold text-background outline-none transition-colors hover:bg-foreground/90 focus-visible:ring-2 focus-visible:ring-accent"
            onClick={() => void handleCopy()}
            type="button"
          >
            {copied ? "Copied" : "Copy"}
          </button>
        </div>
        <div className="mt-5 flex justify-end">
          <button
            className="min-h-11 rounded-xl border border-border-default px-5 text-sm font-semibold text-foreground outline-none transition-colors hover:bg-surface-2 focus-visible:ring-2 focus-visible:ring-accent"
            onClick={onDismiss}
            type="button"
          >
            I&apos;ve saved it
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}

type ApiKeysPanelProps = {
  apiKeys: ApiKeyResponse[];
  onCreate: (name: string, scopes: string[]) => Promise<void>;
  onRevoke: (apiKeyId: string) => Promise<void>;
  onClearRawKey: () => void;
  rawApiKey: string | null;
};

/**
 * Scopes a key can be granted, in the order they are offered.
 *
 * Every key used to receive all of these regardless of what the integration
 * needed, so a Partner that only read the catalog held a key that could also
 * charge their customers. Each is now chosen deliberately.
 */
const API_KEY_SCOPES: { scope: string; label: string; detail: string }[] = [
  {
    scope: "catalog:read",
    label: "Read the catalog",
    detail: "List and open published Frameworks.",
  },
  {
    scope: "preview:read",
    label: "Read previews",
    detail: "Fetch the redacted preview artifact for a Framework.",
  },
  {
    scope: "attestations:read",
    label: "Read attestations",
    detail: "See which Attestors have verified a Framework.",
  },
  {
    scope: "purchase:write",
    label: "Start purchases",
    detail: "Charge a buyer for a Framework. Grant this sparingly.",
  },
  {
    scope: "purchases:read",
    label: "Read purchase status",
    detail: "Check an order it started, without being able to charge.",
  },
];

const DEFAULT_SCOPES = ["catalog:read"];

export function ApiKeysPanel({
  apiKeys,
  onCreate,
  onRevoke,
  onClearRawKey,
  rawApiKey,
}: ApiKeysPanelProps) {
  const nameId = useId();
  const scopesId = useId();
  const [name, setName] = useState("");
  const [scopes, setScopes] = useState<string[]>(DEFAULT_SCOPES);
  const [isCreating, setIsCreating] = useState(false);

  // The API rejects an empty scope list, so the form does too rather than
  // letting a Partner submit a key that can do nothing.
  const canSubmit = isNonEmpty(name) && scopes.length > 0 && !isCreating;

  function toggleScope(scope: string) {
    setScopes((current) =>
      current.includes(scope)
        ? current.filter((entry) => entry !== scope)
        : [...current, scope],
    );
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsCreating(true);
    try {
      // Sent in the declared order rather than the order they were clicked, so
      // two keys with the same access read identically in the list below.
      await onCreate(
        name,
        API_KEY_SCOPES.map((entry) => entry.scope).filter((scope) =>
          scopes.includes(scope),
        ),
      );
      setName("");
      setScopes(DEFAULT_SCOPES);
    } finally {
      setIsCreating(false);
    }
  }

  return (
    <section className="rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm">
      <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
        API keys
      </p>
      <h2 className="mt-1 font-heading text-xl font-bold">Partner API access</h2>
      {rawApiKey ? (
        <OneTimeKeyModal onDismiss={onClearRawKey} value={rawApiKey} />
      ) : null}
      <form className="mt-5 grid gap-4" onSubmit={handleSubmit}>
        <label className="grid gap-2 text-sm font-semibold" htmlFor={nameId}>
          Key name
          <input
            className="min-h-12 rounded-xl border border-border-default bg-surface-2 px-3 font-normal outline-none transition-all focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-50"
            id={nameId}
            onChange={(event) => setName(event.target.value)}
            required
            disabled={isCreating}
            value={name}
            placeholder="e.g. Staging Integration Key"
          />
        </label>
        <fieldset className="grid gap-2" id={scopesId}>
          <legend className="text-sm font-semibold">Access</legend>
          <p className="text-xs text-foreground-muted">
            Grant only what this integration needs. A key that leaks can do
            everything it was given.
          </p>
          <div className="mt-1 grid gap-2">
            {API_KEY_SCOPES.map((entry) => (
              <label
                className="flex min-h-12 cursor-pointer items-start gap-3 rounded-xl border border-border-default bg-surface-2 px-3 py-3 transition-colors hover:bg-surface-1"
                key={entry.scope}
              >
                <input
                  checked={scopes.includes(entry.scope)}
                  className="mt-0.5 h-5 w-5 flex-shrink-0 accent-accent outline-none focus-visible:ring-2 focus-visible:ring-accent"
                  disabled={isCreating}
                  onChange={() => toggleScope(entry.scope)}
                  type="checkbox"
                  value={entry.scope}
                />
                <span className="grid gap-0.5">
                  <span className="text-sm font-semibold text-foreground">
                    {entry.label}
                  </span>
                  <span className="text-xs text-foreground-muted">
                    {entry.detail}
                  </span>
                  <code className="mt-0.5 font-mono text-[11px] text-foreground-subtle">
                    {entry.scope}
                  </code>
                </span>
              </label>
            ))}
          </div>
        </fieldset>
        <button
          className="min-h-12 w-full sm:w-auto sm:justify-self-start rounded-xl shadow-sm outline-none transition-all focus-visible:ring-2 focus-visible:ring-accent bg-foreground hover:bg-foreground/90 px-4 text-sm font-semibold text-background disabled:cursor-not-allowed disabled:opacity-60"
          disabled={!canSubmit}
          type="submit"
        >
          {isCreating ? "Creating..." : "Create key"}
        </button>
      </form>
      <div className="mt-5 grid gap-2">
        {apiKeys.map((apiKey) => (
          <div
            className="flex flex-col sm:flex-row sm:items-start justify-between gap-3 rounded-xl border border-border-default bg-surface-2 p-3"
            key={apiKey.id}
          >
            <div className="min-w-0 flex-1">
              <p className="text-sm font-semibold">{apiKey.name}</p>
              <div className="mt-2 flex flex-wrap items-center gap-1.5">
                <code className="rounded bg-surface-3 px-1.5 py-0.5 font-mono text-xs text-foreground border border-border-default">
                  {apiKey.key_prefix}
                </code>
                {apiKey.scopes.map((scope) => (
                  <span
                    key={scope}
                    className="rounded bg-surface-3 px-1.5 py-0.5 text-[10px] text-foreground-muted border border-border-default"
                  >
                    {scope}
                  </span>
                ))}
                <span
                  className={`rounded-badge px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.05em] border ${
                    apiKey.status === "active"
                      ? "bg-success/10 text-success border-success/30"
                      : "bg-error/10 text-error border-error/30"
                  }`}
                >
                  {formatLabel(apiKey.status)}
                </span>
              </div>
            </div>
            {apiKey.status === "active" ? (
              <button
                className="min-h-12 sm:min-h-9 w-full sm:w-auto shrink-0 rounded-lg border border-error/50 bg-error/5 px-3 text-xs font-semibold text-error outline-none transition-colors hover:bg-error/10 focus-visible:ring-2 focus-visible:ring-error"
                onClick={() => void onRevoke(apiKey.id)}
                type="button"
              >
                Revoke
              </button>
            ) : null}
          </div>
        ))}
      </div>

      <p className="mt-4 text-xs text-foreground-muted">
        Keys are rate-limited per minute and their scopes are fixed once
        created. To change what a key can do, create a new one and revoke the
        old. See usage examples below.
      </p>
    </section>
  );
}

type WebhooksPanelProps = {
  onCreate: (url: string, events: string[]) => Promise<void>;
  onDelete: (webhookId: string) => Promise<void>;
  oneTimeSecret: string | null;
  webhooks: PartnerWebhookResponse[];
};

/**
 * Render outbound webhook registration and endpoint list.
 *
 * @param props - Webhook rows, create/delete callbacks, and one-time raw secret.
 */
export function WebhooksPanel({
  onCreate,
  onDelete,
  oneTimeSecret,
  webhooks,
}: WebhooksPanelProps) {
  const urlId = useId();
  const [selectedEvents, setSelectedEvents] = useState(["purchase.confirmed"]);
  const [url, setUrl] = useState("");
  const [isRegistering, setIsRegistering] = useState(false);
  const [urlError, setUrlError] = useState<string | null>(null);

  const canSubmit = allValid(isHttpUrl(url), selectedEvents.length > 0) && !isRegistering;

  const handleUrlChange = (value: string) => {
    setUrl(value);
    if (value.trim() === "" || isHttpUrl(value)) {
      setUrlError(null);
    } else {
      setUrlError("Please enter a valid URL starting with http:// or https://");
    }
  };

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!isHttpUrl(url)) {
      setUrlError("Please enter a valid URL starting with http:// or https://");
      return;
    }
    setIsRegistering(true);
    try {
      await onCreate(url, selectedEvents);
      setUrl("");
      setUrlError(null);
    } finally {
      setIsRegistering(false);
    }
  }

  return (
    <section className="rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm">
      <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
        Webhooks
      </p>
      <h2 className="mt-1 font-heading text-xl font-bold">Outbound events</h2>
      {oneTimeSecret ? (
        <SecretReveal
          label="Save this webhook secret now — shown only once"
          value={oneTimeSecret}
        />
      ) : null}
      <form className="mt-5 grid gap-3" onSubmit={handleSubmit}>
        <label className="grid gap-2 text-sm font-semibold" htmlFor={urlId}>
          Endpoint URL
          <input
            className={`min-h-12 rounded-xl border bg-surface-2 px-3 font-normal outline-none transition-all focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-50 ${
              urlError ? "border-error focus-visible:ring-error" : "border-border-default"
            }`}
            id={urlId}
            onChange={(event) => handleUrlChange(event.target.value)}
            required
            type="url"
            disabled={isRegistering}
            value={url}
            placeholder="https://yourdomain.com/webhooks"
          />
          {urlError ? (
            <span className="text-xs text-error font-normal">{urlError}</span>
          ) : null}
        </label>
        <div className="grid gap-2">
          {webhookEvents.map((eventName) => (
            <label
              className="flex min-h-12 items-center gap-3 text-sm"
              key={eventName}
            >
              <input
                checked={selectedEvents.includes(eventName)}
                disabled={isRegistering}
                onChange={(event) => {
                  setSelectedEvents((current) =>
                    event.target.checked
                      ? [...current, eventName]
                      : current.filter((item) => item !== eventName),
                  );
                }}
                type="checkbox"
              />
              {eventName}
            </label>
          ))}
        </div>
        <button
          className="min-h-12 w-full sm:w-fit sm:px-6 rounded-xl shadow-sm outline-none transition-all focus-visible:ring-2 focus-visible:ring-accent bg-foreground hover:bg-foreground/90 text-sm font-semibold text-background disabled:cursor-not-allowed disabled:opacity-60"
          disabled={!canSubmit}
          type="submit"
        >
          {isRegistering ? "Registering..." : "Register webhook"}
        </button>
      </form>
      <div className="mt-5 grid gap-2">
        {webhooks.map((webhook) => (
          <div
            className="flex flex-col sm:flex-row sm:items-start justify-between gap-3 rounded-xl border border-border-default bg-surface-2 p-3"
            key={webhook.id}
          >
            <div className="min-w-0 flex-1">
              <p className="break-all text-sm font-semibold">{webhook.url}</p>
              <p className="mt-1 font-mono text-xs text-foreground-muted">
                Signing secret {webhook.secret_hint}
              </p>
              <div className="mt-2 flex flex-wrap items-center gap-1.5">
                {webhook.events.map((event) => (
                  <span
                    key={event}
                    className="rounded bg-surface-3 px-1.5 py-0.5 text-[10px] text-foreground-muted border border-border-default font-mono"
                  >
                    {event}
                  </span>
                ))}
                <span
                  className={`rounded-badge px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.05em] border ${
                    webhook.active
                      ? "bg-success/10 text-success border-success/30"
                      : "bg-error/10 text-error border-error/30"
                  }`}
                >
                  {webhook.active ? "Active" : "Inactive"}
                </span>
              </div>
            </div>
            <button
              className="min-h-12 sm:min-h-9 w-full sm:w-auto shrink-0 rounded-lg border border-error/50 bg-error/5 px-3 text-xs font-semibold text-error outline-none transition-colors hover:bg-error/10 focus-visible:ring-2 focus-visible:ring-error"
              onClick={() => void onDelete(webhook.id)}
              type="button"
            >
              Delete
            </button>
          </div>
        ))}
      </div>
    </section>
  );
}

