"use client";

/**
 * Closing actions for a settled Attestation: rate the attestor and take the
 * tax invoice.
 *
 * Both endpoints existed with no UI, so a requestor finished a review with no
 * way to feed the attestor's reputation or to get the document their finance
 * team needs. Rating is once-only; a second attempt is reported as already
 * done rather than as an error.
 *
 * Maps to: docs/superpowers/specs/2026-09-14-attestation-request-to-report-design.md §2.
 */
import { useState } from "react";

import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import {
  getAttestationInvoiceV1AttestationsAttestationIdInvoiceGet,
  rateAttestationV1AttestationsAttestationIdRatingPost,
} from "@/lib/generated/sdk.gen";
import { Textarea } from "@/components/ui/textarea";

const STARS = [1, 2, 3, 4, 5];

/**
 * Render the rate-the-attestor and download-invoice card.
 *
 * @param props - Attestation id the rating and invoice belong to.
 */
export function AttestationRatingCard({
  attestationId,
}: {
  attestationId: string;
}) {
  const [stars, setStars] = useState(0);
  const [comment, setComment] = useState("");
  const [rated, setRated] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [invoiceNotice, setInvoiceNotice] = useState<string | null>(null);

  /** Submit the star rating, treating a duplicate as already rated. */
  async function handleRate() {
    setError(null);
    setBusy(true);
    try {
      configureBrowserClient();
      const result = await rateAttestationV1AttestationsAttestationIdRatingPost({
        body: { stars, comment: comment.trim() || null },
        headers: getAccessTokenHeaders(),
        path: { attestation_id: attestationId },
      });
      // A second rating is not a failure: the first one stands, and the
      // requestor only needs to be told the job is already done.
      if (result.response.ok || result.response.status === 409) {
        setRated(true);
        return;
      }
      setError(describeGeneratedError(result.error));
    } finally {
      setBusy(false);
    }
  }

  /**
   * Fetch the tax invoice and hand it to the browser.
   *
   * The endpoint redirects to a short-lived private URL once the PDF exists
   * and answers 202 while it is still being rendered.
   */
  async function handleInvoice() {
    setError(null);
    setInvoiceNotice(null);
    setBusy(true);
    try {
      configureBrowserClient();
      const result =
        await getAttestationInvoiceV1AttestationsAttestationIdInvoiceGet({
          headers: getAccessTokenHeaders(),
          path: { attestation_id: attestationId },
        });
      if (result.response.status === 202) {
        setInvoiceNotice("The invoice is being prepared. Try again in a moment.");
        return;
      }
      if (!result.response.ok) {
        setError(describeGeneratedError(result.error));
        return;
      }
      const url = result.data?.download_url ?? null;
      if (!url) {
        setInvoiceNotice("The invoice is being prepared. Try again in a moment.");
        return;
      }
      window.open(url, "_blank", "noopener");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm">
      <h2 className="font-heading text-xl font-bold text-foreground">
        Rate the attestor
      </h2>
      {rated ? (
        <p className="mt-2 text-sm text-foreground-muted">
          You have rated this attestation.
        </p>
      ) : (
        <>
          <p className="mt-1 text-sm text-foreground-muted">
            Your rating feeds the attestor organization&apos;s public record.
            You can rate once.
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            {STARS.map((value) => (
              <button
                aria-label={`${value} stars`}
                aria-pressed={stars === value}
                className={`min-h-12 min-w-12 rounded-xl border text-base font-semibold outline-none transition focus-visible:ring-2 focus-visible:ring-accent ${
                  value <= stars
                    ? "border-accent bg-accent/10 text-accent"
                    : "border-border-default bg-surface-1 text-foreground-muted hover:bg-surface-2"
                }`}
                key={value}
                onClick={() => setStars(value)}
                type="button"
              >
                {value}
              </button>
            ))}
          </div>
          <label className="mt-4 grid gap-2 text-sm font-semibold text-foreground">
            Comment (optional)
            <Textarea
              onChange={(event) => setComment(event.target.value)}
              value={comment}
            />
          </label>
          <button
            className="mt-3 min-h-12 rounded-xl bg-foreground px-6 text-sm font-semibold text-background shadow-sm outline-none transition hover:bg-foreground/90 focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-60"
            disabled={busy || stars === 0}
            onClick={handleRate}
            type="button"
          >
            Submit rating
          </button>
        </>
      )}

      <div className="mt-5 border-t border-border-default pt-4">
        <button
          className="min-h-12 rounded-xl border border-border-default bg-surface-1 px-6 text-sm font-semibold text-foreground outline-none transition hover:bg-surface-2 focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-60"
          disabled={busy}
          onClick={handleInvoice}
          type="button"
        >
          Download invoice
        </button>
        {invoiceNotice ? (
          <p className="mt-2 text-sm text-foreground-muted">{invoiceNotice}</p>
        ) : null}
      </div>

      {error ? <p className="mt-3 text-sm text-error">{error}</p> : null}
    </div>
  );
}
