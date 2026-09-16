"use client";

/**
 * Monthly statement download and the one-off Paystack fee backfill.
 *
 * Statements are Lagos-time months and come back as a CSV file. The fee
 * backfill is super-admin only and runs in the background; the card only
 * confirms it was queued.
 *
 * Maps to: platform treasury design, decisions 7 and 11.
 */
import { useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/select";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import { recentStatementMonths } from "@/lib/financials/treasury";
import {
  adminRequestFeeBackfillV1AdminTreasuryFeeBackfillPost as requestFeeBackfill,
  adminTreasuryStatementV1AdminTreasuryStatementsMonthGet as downloadStatement,
} from "@/lib/generated/sdk.gen";

/**
 * Hand a downloaded file to the browser.
 *
 * @param blob - File contents.
 * @param filename - Suggested file name.
 */
function saveFile(blob: Blob, filename: string): void {
  if (typeof URL.createObjectURL !== "function") {
    return;
  }
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

/**
 * Render the statement and fee backfill card.
 *
 * @param canBackfill - Whether the viewer is the super-admin.
 */
export function StatementCard({ canBackfill }: { canBackfill: boolean }) {
  const months = useMemo(() => recentStatementMonths(new Date(), 12), []);
  const [month, setMonth] = useState(months[0]);
  const [downloading, setDownloading] = useState(false);
  const [backfilling, setBackfilling] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function download() {
    setDownloading(true);
    setError(null);
    configureBrowserClient();
    const result = await downloadStatement({
      headers: getAccessTokenHeaders(),
      path: { month },
      parseAs: "blob",
    });
    setDownloading(false);
    if (!result.response.ok || !(result.data instanceof Blob)) {
      setError(describeGeneratedError(result.error));
      return;
    }
    saveFile(result.data, `auracles-treasury-NGN-${month}.csv`);
  }

  async function backfill() {
    setBackfilling(true);
    setError(null);
    configureBrowserClient();
    const result = await requestFeeBackfill({ headers: getAccessTokenHeaders() });
    setBackfilling(false);
    if (!result.response.ok) {
      setError(describeGeneratedError(result.error));
      return;
    }
    setMessage("Fee backfill queued. Figures update as past fees are found.");
  }

  return (
    <section className="rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm">
      <h3 className="font-heading text-lg font-bold text-foreground">Monthly statement</h3>
      <p className="mt-1 text-sm text-foreground-muted">
        Opening and closing balance, every line in between, and users&apos; money at
        month end. Months follow Lagos time.
      </p>
      <div className="mt-4 flex flex-col gap-2 sm:flex-row">
        <label className="sr-only" htmlFor="treasury-statement-month">
          Statement month
        </label>
        <Select
          id="treasury-statement-month"
          onChange={(event) => setMonth(event.target.value)}
          value={month}
        >
          {months.map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </Select>
        <Button loading={downloading} onClick={() => void download()} variant="secondary">
          Download CSV
        </Button>
      </div>
      {canBackfill ? (
        <div className="mt-5 border-t border-border-default pt-4">
          <p className="text-sm text-foreground-muted">
            Look up Paystack fees on charges made before fees were recorded. Safe to run again.
          </p>
          <Button
            className="mt-3"
            loading={backfilling}
            onClick={() => void backfill()}
            variant="secondary"
          >
            Backfill fees
          </Button>
        </div>
      ) : null}
      {message ? (
        <p className="mt-3 text-sm text-success" role="status">
          {message}
        </p>
      ) : null}
      {error ? <p className="mt-3 text-sm text-error">{error}</p> : null}
    </section>
  );
}
