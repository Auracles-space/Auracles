"use client";

/**
 * Developer portal action controls.
 *
 * Contains the interactive Partner Developer forms for API keys, webhooks, and
 * payout requests so the main portal container stays focused on data loading.
 */
import type { FormEvent } from "react";
import { useId, useState } from "react";

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

type ApiKeysPanelProps = {
  apiKeys: ApiKeyResponse[];
  onCreate: (name: string, scopes: string[]) => Promise<void>;
  onRevoke: (apiKeyId: string) => Promise<void>;
  rawApiKey: string | null;
};

export function ApiKeysPanel({
  apiKeys,
  onCreate,
  onRevoke,
  rawApiKey,
}: ApiKeysPanelProps) {
  const nameId = useId();
  const [name, setName] = useState("");
  const [isCreating, setIsCreating] = useState(false);

  const canSubmit = isNonEmpty(name) && !isCreating;

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsCreating(true);
    try {
      await onCreate(name, ["catalog:read", "preview:read", "purchase:write"]);
      setName("");
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
        <p className="mt-4 rounded-xl border border-warning/30 bg-warning/10 p-3 text-sm text-warning">
          Save this API key now: {rawApiKey}
        </p>
      ) : null}
      <form
        className="mt-5 flex flex-col gap-3 sm:flex-row"
        onSubmit={handleSubmit}
      >
        <label className="grid flex-1 gap-2 text-sm font-semibold" htmlFor={nameId}>
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
        <button
          className="min-h-12 self-end rounded-xl shadow-sm outline-none transition-all focus-visible:ring-2 focus-visible:ring-accent bg-foreground hover:bg-foreground/90 px-4 text-sm font-semibold text-background disabled:cursor-not-allowed disabled:opacity-60"
          disabled={!canSubmit}
          type="submit"
        >
          {isCreating ? "Creating..." : "Create key"}
        </button>
      </form>
      <div className="mt-5 grid gap-2">
        {apiKeys.map((apiKey) => (
          <div
            className="flex items-start justify-between gap-3 rounded-xl border border-border-default bg-surface-2 p-3"
            key={apiKey.id}
          >
            <div className="min-w-0">
              <p className="text-sm font-semibold">{apiKey.name}</p>
              <p className="mt-1 text-sm text-foreground-muted break-words">
                {apiKey.key_prefix} · {formatLabel(apiKey.status)} ·{" "}
                {apiKey.scopes.join(", ")}
              </p>
            </div>
            {apiKey.status === "active" ? (
              <button
                className="min-h-9 shrink-0 rounded-lg border border-error/50 bg-error/5 px-3 text-xs font-semibold text-error outline-none transition-colors hover:bg-error/10 focus-visible:ring-2 focus-visible:ring-error"
                onClick={() => void onRevoke(apiKey.id)}
                type="button"
              >
                Revoke
              </button>
            ) : null}
          </div>
        ))}
      </div>
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
        <p className="mt-4 rounded-xl border border-warning/30 bg-warning/10 p-3 text-sm text-warning">
          Save this webhook secret now: {oneTimeSecret}
        </p>
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
          className="min-h-12 rounded-xl shadow-sm outline-none transition-all focus-visible:ring-2 focus-visible:ring-accent bg-foreground hover:bg-foreground/90 px-4 text-sm font-semibold text-background disabled:cursor-not-allowed disabled:opacity-60"
          disabled={!canSubmit}
          type="submit"
        >
          {isRegistering ? "Registering..." : "Register webhook"}
        </button>
      </form>
      <div className="mt-5 grid gap-2">
        {webhooks.map((webhook) => (
          <div
            className="flex items-start justify-between gap-3 rounded-xl border border-border-default bg-surface-2 p-3"
            key={webhook.id}
          >
            <div className="min-w-0">
              <p className="break-all text-sm font-semibold">{webhook.url}</p>
              <p className="mt-1 text-sm text-foreground-muted">
                {webhook.events.join(", ")} ·{" "}
                {webhook.active ? "Active" : "Inactive"}
              </p>
            </div>
            <button
              className="min-h-9 shrink-0 rounded-lg border border-error/50 bg-error/5 px-3 text-xs font-semibold text-error outline-none transition-colors hover:bg-error/10 focus-visible:ring-2 focus-visible:ring-error"
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
