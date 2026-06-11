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
import { formatLabel } from "@/lib/marketplace/format";

const webhookEvents = [
  "purchase.confirmed",
  "commission.cleared",
  "framework.updated",
];

type ApiKeysPanelProps = {
  apiKeys: ApiKeyResponse[];
  onCreate: (name: string, scopes: string[]) => Promise<void>;
  rawApiKey: string | null;
};

/**
 * Render Partner API key list and creation form.
 *
 * @param props - Current API keys, create callback, and one-time raw key.
 */
export function ApiKeysPanel({ apiKeys, onCreate, rawApiKey }: ApiKeysPanelProps) {
  const nameId = useId();
  const [name, setName] = useState("");

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await onCreate(name, ["catalog:read", "preview:read", "purchase:write"]);
    setName("");
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
            className="min-h-11 rounded-xl border border-border-default bg-surface-2 px-3 font-normal outline-none transition-all focus-visible:ring-2 focus-visible:ring-accent"
            id={nameId}
            onChange={(event) => setName(event.target.value)}
            required
            value={name}
          />
        </label>
        <button
          className="min-h-11 self-end rounded-xl shadow-sm outline-none transition-all focus-visible:ring-2 focus-visible:ring-accent bg-foreground hover:bg-foreground/90 px-4 text-sm font-semibold text-background"
          type="submit"
        >
          Create key
        </button>
      </form>
      <div className="mt-5 grid gap-2">
        {apiKeys.map((apiKey) => (
          <div
            className="rounded-xl border border-border-default bg-surface-2 p-3"
            key={apiKey.id}
          >
            <p className="text-sm font-semibold">{apiKey.name}</p>
            <p className="mt-1 text-sm text-foreground-muted">
              {apiKey.key_prefix} · {formatLabel(apiKey.status)} ·{" "}
              {apiKey.scopes.join(", ")}
            </p>
          </div>
        ))}
      </div>
    </section>
  );
}

type WebhooksPanelProps = {
  onCreate: (url: string, events: string[]) => Promise<void>;
  oneTimeSecret: string | null;
  webhooks: PartnerWebhookResponse[];
};

/**
 * Render outbound webhook registration and endpoint list.
 *
 * @param props - Webhook rows, create callback, and one-time raw secret.
 */
export function WebhooksPanel({
  onCreate,
  oneTimeSecret,
  webhooks,
}: WebhooksPanelProps) {
  const urlId = useId();
  const [selectedEvents, setSelectedEvents] = useState(["purchase.confirmed"]);
  const [url, setUrl] = useState("");

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await onCreate(url, selectedEvents);
    setUrl("");
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
            className="min-h-11 rounded-xl border border-border-default bg-surface-2 px-3 font-normal outline-none transition-all focus-visible:ring-2 focus-visible:ring-accent"
            id={urlId}
            onChange={(event) => setUrl(event.target.value)}
            required
            type="url"
            value={url}
          />
        </label>
        <div className="grid gap-2">
          {webhookEvents.map((eventName) => (
            <label
              className="flex min-h-11 items-center gap-3 text-sm"
              key={eventName}
            >
              <input
                checked={selectedEvents.includes(eventName)}
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
          className="min-h-11 rounded-xl shadow-sm outline-none transition-all focus-visible:ring-2 focus-visible:ring-accent bg-foreground hover:bg-foreground/90 px-4 text-sm font-semibold text-background"
          type="submit"
        >
          Register webhook
        </button>
      </form>
      <div className="mt-5 grid gap-2">
        {webhooks.map((webhook) => (
          <div
            className="rounded-xl border border-border-default bg-surface-2 p-3"
            key={webhook.id}
          >
            <p className="break-all text-sm font-semibold">{webhook.url}</p>
            <p className="mt-1 text-sm text-foreground-muted">
              {webhook.events.join(", ")} · {webhook.active ? "Active" : "Inactive"}
            </p>
          </div>
        ))}
      </div>
    </section>
  );
}
