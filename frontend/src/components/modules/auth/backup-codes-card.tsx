"use client";

/**
 * Backup codes display with a one-click copy control.
 *
 * Shown once after enrollment or regeneration — backup codes are never
 * retrievable later, so the card nudges the user to copy and store them.
 */
import { useState } from "react";

type BackupCodesCardProps = {
  codes: string[];
};

/**
 * Render the one-time backup codes alongside a copy-to-clipboard action.
 *
 * @param props - The freshly issued backup codes to display.
 */
export function BackupCodesCard({ codes }: BackupCodesCardProps) {
  const [copied, setCopied] = useState(false);

  async function copyCodes(): Promise<void> {
    await navigator.clipboard.writeText(codes.join("\n"));
    setCopied(true);
  }

  return (
    <div className="rounded-[20px] border border-border-strong bg-surface-2 p-4 shadow-sm">
      <div className="flex items-center justify-between gap-3">
        <h3 className="font-heading text-sm font-semibold text-foreground">
          Backup codes
        </h3>
        <button
          className="inline-flex min-h-9 items-center justify-center rounded-lg border border-border-default bg-background px-3 py-1.5 text-xs font-medium text-foreground transition hover:bg-surface-1"
          onClick={() => void copyCodes()}
          type="button"
        >
          {copied ? "Copied" : "Copy codes"}
        </button>
      </div>
      <p className="mt-2 text-xs leading-5 text-foreground-muted">
        Store these somewhere safe. Each code works once and lets you sign in if
        you lose your authenticator device.
      </p>
      <ul className="mt-3 grid gap-2 text-sm text-foreground-muted sm:grid-cols-2">
        {codes.map((code) => (
          <li className="font-mono" key={code}>
            {code}
          </li>
        ))}
      </ul>
    </div>
  );
}
