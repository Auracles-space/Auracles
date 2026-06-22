"use client";

/**
 * Partner API usage examples.
 *
 * Renders copy-ready TypeScript snippets for every supported Partner API
 * request. When a key was just created the raw value is inlined so the
 * developer can copy a working call directly; otherwise a `<your-key>`
 * placeholder is shown (the raw key is only ever returned once).
 */
import { useState } from "react";

const PARTNER_API_BASE = `${
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"
}/v1/partner`;

type UsageExample = {
  title: string;
  description: string;
  code: string;
};

/**
 * Build the snippet list for the given API key (or placeholder).
 *
 * @param key - Raw API key to inline, or a placeholder when unavailable.
 */
function buildExamples(key: string): UsageExample[] {
  const base = PARTNER_API_BASE;
  const headers = `{ "X-API-Key": "${key}" }`;
  return [
    {
      title: "Search the catalog",
      description: "GET /catalog — browse published frameworks with filters.",
      code: `const res = await fetch(
  "${base}/catalog?q=strategy&page=1&page_size=20&sort=newest",
  { headers: ${headers} },
);
const { items, total } = await res.json();`,
    },
    {
      title: "Get framework detail",
      description: "GET /catalog/{id} — public detail for one framework.",
      code: `const frameworkId = "00000000-0000-0000-0000-000000000000";
const res = await fetch(\`${base}/catalog/\${frameworkId}\`, {
  headers: ${headers},
});
const framework = await res.json();`,
    },
    {
      title: "Get the preview artifact",
      description: "GET /catalog/{id}/preview — short-lived preview URL.",
      code: `const res = await fetch(
  \`${base}/catalog/\${frameworkId}/preview\`,
  { headers: ${headers} },
);
const preview = await res.json();`,
    },
    {
      title: "List attestations",
      description: "GET /catalog/{id}/attestations — public trust signals.",
      code: `const res = await fetch(
  \`${base}/catalog/\${frameworkId}/attestations\`,
  { headers: ${headers} },
);
const { attestations } = await res.json();`,
    },
    {
      title: "Start a purchase",
      description:
        "POST /frameworks/{id}/purchase — partner-attributed Stripe checkout.",
      code: `const res = await fetch(
  \`${base}/frameworks/\${frameworkId}/purchase\`,
  {
    method: "POST",
    headers: {
      "X-API-Key": "${key}",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      buyer_email: "buyer@example.com",
      // "single_user" | "team" | "organizational"
      license_type: "single_user",
    }),
  },
);
const { checkout_url, transaction_id } = await res.json();`,
    },
    {
      title: "Check a purchase status",
      description: "GET /purchases/{transaction_id} — poll your purchase.",
      code: `const res = await fetch(
  \`${base}/purchases/\${transaction_id}\`,
  { headers: ${headers} },
);
const status = await res.json();`,
    },
  ];
}

/**
 * One usage snippet with a copy-to-clipboard control.
 *
 * @param props.example - The example to render.
 */
function UsageCard({ example }: { example: UsageExample }) {
  const [copied, setCopied] = useState(false);

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(example.code);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  }

  return (
    <div className="rounded-xl border border-border-default bg-surface-2 p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm font-semibold text-foreground">{example.title}</p>
          <p className="mt-0.5 text-xs text-foreground-muted">
            {example.description}
          </p>
        </div>
        <button
          className="min-h-9 shrink-0 rounded-lg border border-border-default bg-surface-1 px-3 text-xs font-semibold text-foreground outline-none transition-colors hover:bg-surface-2 focus-visible:ring-2 focus-visible:ring-accent"
          onClick={() => void handleCopy()}
          type="button"
        >
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <pre className="mt-3 overflow-x-auto rounded-lg bg-background p-3 text-xs leading-5 text-foreground">
        <code>{example.code}</code>
      </pre>
    </div>
  );
}

/**
 * Render copy-ready Partner API usage examples for all supported requests.
 *
 * @param props.apiKey - Raw API key to inline, or null for a placeholder.
 */
export function DeveloperApiUsage({ apiKey }: { apiKey: string | null }) {
  const key = apiKey ?? "<your-key>";
  const examples = buildExamples(key);

  return (
    <section className="rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm">
      <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
        Usage
      </p>
      <h2 className="mt-1 font-heading text-xl font-bold">Partner API examples</h2>
      <p className="mt-2 text-sm text-foreground-muted">
        {apiKey
          ? "Your new key is inlined below — copy a working call directly."
          : "Snippets use a <your-key> placeholder. Create a key to inline a working value."}
      </p>
      <div className="mt-5 grid gap-3">
        {examples.map((example) => (
          <UsageCard example={example} key={example.title} />
        ))}
      </div>
    </section>
  );
}
