"use client";

/**
 * Partner webhook verification examples.
 *
 * Shows a partner how to receive and verify outbound Auracles webhooks. The
 * signing secret is returned exactly once on registration, so when it is
 * available it is inlined into the snippet; otherwise a placeholder is shown.
 */
import { useState } from "react";

type WebhookExample = {
  title: string;
  description: string;
  code: string;
};

/**
 * Build the webhook snippet list for the given signing secret (or placeholder).
 *
 * @param secret - Raw webhook secret to inline, or a placeholder.
 */
function buildExamples(secret: string): WebhookExample[] {
  return [
    {
      title: "Verify a webhook (Node / Express)",
      description:
        "Recompute the HMAC over the raw body and reject anything that doesn't match.",
      code: `import express from "express";
import crypto from "crypto";

const SECRET = "${secret}";
const app = express();

// Raw body is required — re-serialized JSON breaks the signature.
app.post(
  "/webhooks/auracles",
  express.raw({ type: "application/json" }),
  (req, res) => {
    const ts = req.header("X-Auracles-Timestamp") ?? "";
    const sig = req.header("X-Auracles-Signature") ?? "";

    const expected = crypto
      .createHmac("sha256", SECRET)
      .update(\`\${ts}.\`)
      .update(req.body)
      .digest("hex");

    const ok =
      sig.length === expected.length &&
      crypto.timingSafeEqual(Buffer.from(sig), Buffer.from(expected));
    if (!ok) return res.status(400).send("bad signature");

    // Replay protection: reject events older than 5 minutes.
    if (Math.abs(Date.now() / 1000 - Number(ts)) > 300) {
      return res.status(400).send("stale");
    }

    const event = JSON.parse(req.body.toString());
    switch (req.header("X-Auracles-Event")) {
      case "purchase.confirmed":
        // mark the buyer's order paid in your system
        break;
      case "commission.cleared":
        // your commission is now withdrawable
        break;
      case "framework.updated":
        // refresh cached catalog data
        break;
    }
    res.sendStatus(200);
  },
);

app.listen(3000);`,
    },
    {
      title: "Verify a webhook (TypeScript, Web standard)",
      description: "Framework-agnostic verifier for Fetch-style Request handlers.",
      code: `const SECRET = "${secret}";

export async function verifyAuraclesWebhook(request: Request): Promise<unknown> {
  const ts = request.headers.get("X-Auracles-Timestamp") ?? "";
  const sig = request.headers.get("X-Auracles-Signature") ?? "";
  const raw = new Uint8Array(await request.arrayBuffer());

  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(SECRET),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const signed = await crypto.subtle.sign(
    "HMAC",
    key,
    new Uint8Array([...new TextEncoder().encode(\`\${ts}.\`), ...raw]),
  );
  const expected = [...new Uint8Array(signed)]
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");

  if (sig !== expected) throw new Error("bad signature");
  if (Math.abs(Date.now() / 1000 - Number(ts)) > 300) throw new Error("stale");

  return JSON.parse(new TextDecoder().decode(raw));
}`,
    },
  ];
}

/**
 * One webhook snippet with a copy-to-clipboard control.
 *
 * @param props.example - The example to render.
 */
function WebhookCard({ example }: { example: WebhookExample }) {
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
      <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-foreground">{example.title}</p>
          <p className="mt-0.5 text-xs text-foreground-muted">
            {example.description}
          </p>
        </div>
        <button
          className="min-h-12 sm:min-h-9 w-full sm:w-auto shrink-0 rounded-lg border border-border-default bg-surface-1 px-3 text-xs font-semibold text-foreground outline-none transition-colors hover:bg-surface-2 focus-visible:ring-2 focus-visible:ring-accent"
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
 * Render webhook verification examples for the developer portal.
 *
 * @param props.secret - One-time webhook secret to inline, or null.
 */
export function DeveloperWebhookUsage({ secret }: { secret: string | null }) {
  const value = secret ?? "<your-webhook-secret>";
  const examples = buildExamples(value);

  return (
    <section className="rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm">
      <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
        Webhooks
      </p>
      <h2 className="mt-1 font-heading text-xl font-bold">Verify webhook events</h2>
      <p className="mt-2 text-sm text-foreground-muted">
        Each delivery carries <code className="font-mono">X-Auracles-Event</code>,{" "}
        <code className="font-mono">X-Auracles-Timestamp</code>, and{" "}
        <code className="font-mono">X-Auracles-Signature</code> (HMAC-SHA256 of{" "}
        <code className="font-mono">{`{timestamp}.{raw_body}`}</code>). Verify the
        signature before trusting an event.
      </p>
      {secret ? (
        <p className="mt-2 text-xs text-foreground-muted">
          Your new signing secret is inlined below — store it server-side only.
        </p>
      ) : null}
      <div className="mt-5 grid gap-3">
        {examples.map((example) => (
          <WebhookCard example={example} key={example.title} />
        ))}
      </div>
    </section>
  );
}
