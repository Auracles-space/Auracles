"use client";

/**
 * Admin platform-configuration panel.
 *
 * Reads the editable platform configuration and, for the protected super-admin
 * only, allows changing values in batches with a reason and TOTP confirmation.
 * Ordinary admins see the values read-only with a notice. Changes are grouped
 * by domain so a reviewer can find the right knob quickly.
 *
 * Maps to: FR-ADMIN-009.
 */
import { useEffect, useMemo, useState } from "react";

import { TotpInput } from "@/components/modules/auth/totp-input";
import { Button } from "@/components/ui/button";
import { TableSkeleton } from "@/components/ui/skeletons/table-skeleton";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import { loadCurrentUserSession } from "@/lib/auth/current-user-session";
import {
  listPlatformConfigV1AdminConfigGet,
  updatePlatformConfigV1AdminConfigPatch,
} from "@/lib/generated/sdk.gen";
import type {
  AdminConfigItem,
  AdminConfigUpdateItem,
} from "@/lib/generated/types.gen";

type ConfigKey = AdminConfigUpdateItem["key"];

/** Maximum config changes accepted by the server in a single request. */
const MAX_UPDATES_PER_SAVE = 10;

/**
 * Grouped, human-labelled view of the editable configuration keys.
 *
 * Keys not listed here still render under "Other" so a new server key is never
 * silently hidden from the super-admin.
 */
const CONFIG_GROUPS: { title: string; keys: ConfigKey[] }[] = [
  {
    title: "Financial",
    keys: ["commission_rate", "min_payout_usd", "refund_window_hours"],
  },
  {
    title: "Attestation fees",
    keys: [
      "attestation_fee_framework",
      "attestation_fee_contributor",
      "attestation_fee_operator",
      "attestation_fee_credential",
    ],
  },
  {
    title: "Attestation workflow",
    keys: [
      "attestation_cohort_size",
      "attestation_offer_accept_hours",
      "attestation_dispute_window_days",
      "attestation_completion_sla_days_framework",
      "attestation_completion_sla_days_contributor",
      "attestation_completion_sla_days_operator",
      "attestation_completion_sla_days_credential",
    ],
  },
  {
    title: "Reputation",
    keys: [
      "reputation_weights_framework",
      "reputation_weights_contributor",
      "reputation_weights_operator",
      "reputation_min_activity_framework",
      "reputation_min_activity_contributor",
      "reputation_min_activity_operator",
      "reputation_prior",
      "reputation_prior_strength_k",
      "reputation_dispute_penalty",
    ],
  },
  {
    title: "Privacy & consent",
    keys: [
      "consent_version_terms_of_service",
      "consent_version_privacy_policy",
      "account_deletion_grace_days",
      "data_export_expiry_days",
    ],
  },
  {
    title: "Search",
    keys: ["saved_search_alert_cadence_hours"],
  },
];

/**
 * Turn a config key into a readable field label.
 *
 * @param key - Raw platform-config key.
 */
function labelForKey(key: string): string {
  return key.replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

/**
 * Render the platform-configuration reader/editor for admins.
 */
export function AdminConfigPanel() {
  const [items, setItems] = useState<AdminConfigItem[] | null>(null);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [isSuperadmin, setIsSuperadmin] = useState(false);
  const [reason, setReason] = useState("");
  const [totpCode, setTotpCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState(false);

  useEffect(() => {
    let mounted = true;

    async function load(): Promise<void> {
      configureBrowserClient();
      const [session, config] = await Promise.all([
        loadCurrentUserSession(),
        listPlatformConfigV1AdminConfigGet({ headers: getAccessTokenHeaders() }),
      ]);
      if (!mounted) {
        return;
      }
      setLoading(false);
      if (!config.response.ok || !config.data) {
        setError(describeGeneratedError(config.error));
        return;
      }
      setIsSuperadmin(session?.is_superadmin ?? false);
      setItems(config.data.items);
      setDrafts(
        Object.fromEntries(
          config.data.items.map((item: AdminConfigItem) => [item.key, item.value]),
        ),
      );
    }

    void load();
    return () => {
      mounted = false;
    };
  }, []);

  const itemsByKey = useMemo(
    () => new Map((items ?? []).map((item) => [item.key, item])),
    [items],
  );

  const changedKeys = useMemo(
    () =>
      (items ?? [])
        .filter((item) => item.editable && drafts[item.key] !== item.value)
        .map((item) => item.key),
    [items, drafts],
  );

  const tooManyChanges = changedKeys.length > MAX_UPDATES_PER_SAVE;
  const canSave =
    isSuperadmin &&
    !pending &&
    changedKeys.length > 0 &&
    !tooManyChanges &&
    reason.trim().length > 0 &&
    totpCode.trim().length >= 6;

  async function handleSave(): Promise<void> {
    setPending(true);
    setError(null);
    setNotice(null);
    configureBrowserClient();
    const updates = changedKeys.map<AdminConfigUpdateItem>((key) => ({
      key: key as ConfigKey,
      value: drafts[key],
    }));
    const result = await updatePlatformConfigV1AdminConfigPatch({
      body: { reason: reason.trim(), totp_code: totpCode.trim(), updates },
      headers: getAccessTokenHeaders(),
    });
    setPending(false);
    if (!result.response.ok || !result.data) {
      setError(describeGeneratedError(result.error));
      return;
    }
    setItems(result.data.items);
    setDrafts(
      Object.fromEntries(
        result.data.items.map((item: AdminConfigItem) => [item.key, item.value]),
      ),
    );
    setReason("");
    setTotpCode("");
    setNotice(`Saved ${updates.length} change${updates.length === 1 ? "" : "s"}.`);
  }

  if (loading) {
    return <TableSkeleton />;
  }

  const known = new Set(CONFIG_GROUPS.flatMap((group) => group.keys));
  const otherKeys = (items ?? [])
    .map((item) => item.key)
    .filter((key) => !known.has(key as ConfigKey));
  const groups = otherKeys.length
    ? [...CONFIG_GROUPS, { title: "Other", keys: otherKeys as ConfigKey[] }]
    : CONFIG_GROUPS;

  return (
    <section className="grid gap-6">
      <header className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
        <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
          Admin configuration
        </p>
        <h2 className="mt-2 font-heading text-3xl font-bold text-foreground">
          Platform configuration
        </h2>
        <p className="mt-3 max-w-3xl text-sm leading-6 text-foreground-muted">
          Commission, fees, SLAs, reputation tuning, and privacy windows. Changes
          are reserved for the super-admin and require a reason plus 2FA.
        </p>
      </header>

      {!isSuperadmin ? (
        <div className="rounded-2xl border border-warning/30 bg-warning/10 p-4 text-sm text-warning">
          Read-only: only the super-admin can change platform configuration.
        </div>
      ) : null}
      {error ? (
        <div className="rounded-2xl border border-error/30 bg-error/10 p-4 text-sm text-error">
          {error}
        </div>
      ) : null}
      {notice ? (
        <div className="rounded-2xl border border-success/30 bg-success/10 p-4 text-sm text-success">
          {notice}
        </div>
      ) : null}

      {groups.map((group) => (
        <section
          className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm"
          key={group.title}
        >
          <h3 className="font-heading text-lg font-bold text-foreground">
            {group.title}
          </h3>
          <div className="mt-4 grid gap-4 md:grid-cols-2">
            {group.keys.map((key) => {
              const item = itemsByKey.get(key);
              if (!item) {
                return null;
              }
              const editable = isSuperadmin && item.editable;
              const changed = item.editable && drafts[key] !== item.value;
              return (
                <label
                  className="grid gap-1.5 text-sm font-semibold text-foreground"
                  key={key}
                >
                  <span className="flex items-center gap-2">
                    {labelForKey(key)}
                    {changed ? (
                      <span className="rounded bg-accent/10 px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wide text-accent">
                        changed
                      </span>
                    ) : null}
                  </span>
                  <input
                    className="min-h-12 rounded-xl border border-border-default bg-background px-4 text-sm font-normal text-foreground outline-none transition-colors focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-60"
                    disabled={!editable}
                    onChange={(event) =>
                      setDrafts((current) => ({
                        ...current,
                        [key]: event.target.value,
                      }))
                    }
                    value={drafts[key] ?? ""}
                  />
                </label>
              );
            })}
          </div>
        </section>
      ))}

      {isSuperadmin ? (
        <section className="sticky bottom-4 grid gap-4 rounded-2xl border border-border-default bg-surface-2 p-6 shadow-lg">
          <div className="text-sm font-semibold text-foreground">
            {changedKeys.length === 0
              ? "No changes yet."
              : `${changedKeys.length} change${changedKeys.length === 1 ? "" : "s"} ready to save.`}
          </div>
          {tooManyChanges ? (
            <p className="text-xs text-error">
              Save at most {MAX_UPDATES_PER_SAVE} changes at a time.
            </p>
          ) : null}
          <label className="grid gap-2 text-sm font-semibold text-foreground">
            Reason (audit trail)
            <input
              className="min-h-12 rounded-xl border border-border-default bg-background px-4 text-sm font-normal text-foreground outline-none transition-colors focus-visible:ring-2 focus-visible:ring-accent"
              onChange={(event) => setReason(event.target.value)}
              placeholder="Why are you changing this?"
              value={reason}
            />
          </label>
          <TotpInput onChange={setTotpCode} value={totpCode} />
          <div>
            <Button disabled={!canSave} onClick={() => void handleSave()}>
              Save changes
            </Button>
          </div>
        </section>
      ) : null}
    </section>
  );
}
