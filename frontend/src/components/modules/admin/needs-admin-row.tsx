"use client";

/**
 * One self-contained row in the admin needs-admin attestation queue.
 *
 * Carries its own attestor-org picker, reason, and 2FA so an admin can assign
 * or refund a single request inline — no shared form, no scrolling. Assigning
 * dispatches an offer to the chosen org (the org then staffs its own reviewer);
 * refunding returns the escrowed fee to the requestor.
 */
import { useState } from "react";

import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import {
  adminAssignAttestation,
  adminRefundAttestation,
} from "@/lib/generated/sdk.gen";
import type {
  AttestationRequestResponse,
  AttestorDirectoryEntry,
} from "@/lib/generated/types.gen";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";

type NeedsAdminRowProps = {
  /** The needs-admin attestation this row acts on. */
  attestation: AttestationRequestResponse;
  /** Active attestor orgs for the assign picker. */
  attestorOrgs: AttestorDirectoryEntry[];
  /** Called with the attestation id once it is assigned or refunded. */
  onResolved: (attestationId: string) => void;
};

/**
 * Render inline assign/refund controls for one needs-admin attestation.
 *
 * @param props - The attestation, org options, and resolution callback.
 */
export function NeedsAdminRow({
  attestation,
  attestorOrgs,
  onResolved,
}: NeedsAdminRowProps) {
  const [orgId, setOrgId] = useState("");
  const [reason, setReason] = useState("");
  const [totp, setTotp] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reasonOk = reason.trim().length >= 5;
  const totpOk = totp.trim().length >= 6;
  const canAssign = orgId.length > 0 && reasonOk && totpOk && !busy;
  const canRefund = reasonOk && totpOk && !busy;

  /** Dispatch an offer to the selected org for this request. */
  async function handleAssign() {
    setError(null);
    setBusy(true);
    try {
      configureBrowserClient();
      const result = await adminAssignAttestation({
        body: { attestor_org_id: orgId, reason, totp_code: totp },
        headers: getAccessTokenHeaders(),
        path: { attestation_id: attestation.id },
      });
      if (!result.response.ok || !result.data) {
        setError(describeGeneratedError(result.error));
        return;
      }
      onResolved(attestation.id);
    } finally {
      setBusy(false);
    }
  }

  /** Refund the escrowed fee for this request. */
  async function handleRefund() {
    setError(null);
    setBusy(true);
    try {
      configureBrowserClient();
      const result = await adminRefundAttestation({
        body: { reason, totp_code: totp },
        headers: getAccessTokenHeaders(),
        path: { attestation_id: attestation.id },
      });
      if (!result.response.ok || !result.data) {
        setError(describeGeneratedError(result.error));
        return;
      }
      onResolved(attestation.id);
    } finally {
      setBusy(false);
    }
  }

  return (
    <article className="grid gap-3 rounded-xl border border-border-default bg-surface-1 p-4 shadow-sm">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="font-heading text-sm font-bold text-foreground">
          {attestation.review_type
            ? `${attestation.review_type} review`
            : "Attestation request"}
        </p>
        <p className="text-xs text-foreground-muted">
          {attestation.currency} {attestation.fee_amount}
        </p>
      </div>
      <p className="text-xs text-foreground-muted">{attestation.id}</p>

      <div className="grid gap-3 sm:grid-cols-2">
        <label className="grid gap-1.5 text-xs font-semibold uppercase tracking-wider text-foreground-muted">
          Attestor org
          <Select onChange={(event) => setOrgId(event.target.value)} value={orgId}>
            <option value="">Select an attestor org</option>
            {attestorOrgs.map((org) => (
              <option key={org.org_id} value={org.org_id}>
                {org.name}
              </option>
            ))}
          </Select>
        </label>
        <label className="grid gap-1.5 text-xs font-semibold uppercase tracking-wider text-foreground-muted">
          Reason
          <Input
            onChange={(event) => setReason(event.target.value)}
            placeholder="Reason for this action"
            value={reason}
          />
        </label>
        <label className="grid gap-1.5 text-xs font-semibold uppercase tracking-wider text-foreground-muted">
          Admin 2FA code
          <Input
            inputMode="numeric"
            onChange={(event) => setTotp(event.target.value)}
            placeholder="6-digit code"
            value={totp}
          />
        </label>
      </div>

      {error ? <p className="text-sm text-error">{error}</p> : null}

      <div className="flex flex-wrap gap-3">
        <button
          className="min-h-11 rounded-xl bg-foreground px-5 text-sm font-semibold text-background shadow-sm outline-none transition-all hover:bg-foreground/90 focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-50"
          disabled={!canAssign}
          onClick={handleAssign}
          type="button"
        >
          Assign to org
        </button>
        <button
          className="min-h-11 rounded-xl border border-error px-5 text-sm font-semibold text-error outline-none transition-all hover:bg-error/10 focus-visible:ring-2 focus-visible:ring-error disabled:cursor-not-allowed disabled:opacity-50"
          disabled={!canRefund}
          onClick={handleRefund}
          type="button"
        >
          Refund
        </button>
      </div>
    </article>
  );
}
