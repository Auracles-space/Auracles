"use client";

/**
 * Owner-only dialog for correcting an organization's country.
 *
 * The country picks the payout rail (Nigeria on Paystack, other countries on
 * Stripe) and gives the registration number meaning, so the server refuses
 * the change (409) once business verification is submitted or approved or a
 * payout account is connected; that reason is shown under the field. The
 * PATCH is gated by step-up 2FA server-side; the global step-up interceptor
 * installed by `configureBrowserClient()` prompts and replays.
 *
 * Maps to: docs/superpowers/specs/2026-09-14-organizations-end-to-end-design.md §Country change.
 */
import { useId, useState } from "react";

import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Select } from "@/components/ui/select";
import { useToast } from "@/components/ui/toast";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import { changeOrgCountryV1OrgsOrgIdCountryPatch } from "@/lib/generated/sdk.gen";
import { PAYOUT_COUNTRIES } from "@/lib/marketplace/countries";

import { useOrganization } from "./organization-context";

type OrganizationCountryDialogProps = {
  /** Whether the dialog is visible. */
  open: boolean;
  /** Called when the dialog is dismissed or the change succeeds. */
  onClose: () => void;
};

/**
 * Render the country change dialog for the organization in context.
 *
 * @param props - Open state and close callback.
 */
export function OrganizationCountryDialog({ open, onClose }: OrganizationCountryDialogProps) {
  const { orgId, org, refreshOrganization } = useOrganization();
  const toast = useToast();
  const selectId = useId();
  const [country, setCountry] = useState(org.country);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const changed = country !== org.country;

  async function submit(): Promise<void> {
    if (!changed || busy) return;
    setBusy(true);
    setError(null);
    configureBrowserClient();
    const result = await changeOrgCountryV1OrgsOrgIdCountryPatch({
      body: { country },
      headers: getAccessTokenHeaders(),
      path: { org_id: orgId },
    });
    if (!result.response.ok) {
      // 409 carries the lock reason (verification or payout account).
      setError(describeGeneratedError(result.error));
      setBusy(false);
      return;
    }
    setBusy(false);
    onClose();
    await refreshOrganization();
    toast.success("Country updated.");
  }

  return (
    <ConfirmDialog
      busy={busy}
      confirmDisabled={!changed}
      confirmLabel="Change country"
      description={
        <div className="grid gap-3">
          <p>
            The country picks where payouts settle: Nigeria settles on Paystack, other
            countries on Stripe. It locks once business verification is submitted or a
            payout account is connected.
          </p>
          <div className="grid gap-1.5">
            <label className="text-sm font-semibold text-foreground" htmlFor={selectId}>
              Country
            </label>
            <Select
              aria-invalid={error ? true : undefined}
              id={selectId}
              onChange={(event) => {
                setCountry(event.target.value);
                setError(null);
              }}
              value={country}
            >
              {PAYOUT_COUNTRIES.map((option) => (
                <option key={option.code} value={option.code}>
                  {option.name}
                </option>
              ))}
            </Select>
            {error ? <p className="text-sm text-error">{error}</p> : null}
          </div>
        </div>
      }
      eyebrow="Organization"
      onClose={onClose}
      onConfirm={() => void submit()}
      open={open}
      title="Change country"
    />
  );
}
