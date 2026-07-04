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
import { MagnifyingGlassIcon } from "@radix-ui/react-icons";

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
      "attestation_dispute_window_business_days",
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

  // Layout, search filter, and audit verification modal states
  const [activeGroupTitle, setActiveGroupTitle] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [isConfirmOpen, setIsConfirmOpen] = useState(false);

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

  const groups = useMemo(() => {
    const known = new Set(CONFIG_GROUPS.flatMap((group) => group.keys));
    const otherKeys = (items ?? [])
      .map((item) => item.key)
      .filter((key) => !known.has(key as ConfigKey));
    return otherKeys.length
      ? [...CONFIG_GROUPS, { title: "Other", keys: otherKeys as ConfigKey[] }]
      : CONFIG_GROUPS;
  }, [items]);

  // Load first tab context on panel initialization
  useEffect(() => {
    if (groups.length > 0 && !activeGroupTitle) {
      setActiveGroupTitle(groups[0].title);
    }
  }, [groups, activeGroupTitle]);

  const changedKeys = useMemo(
    () =>
      (items ?? [])
        .filter((item) => item.editable && drafts[item.key] !== item.value)
        .map((item) => item.key),
    [items, drafts],
  );

  const filteredKeys = useMemo(() => {
    if (!searchQuery.trim()) return [];
    const query = searchQuery.toLowerCase().trim();
    return (items ?? []).filter((item) => {
      const keyMatch = item.key.toLowerCase().includes(query);
      const labelMatch = labelForKey(item.key).toLowerCase().includes(query);
      return keyMatch || labelMatch;
    });
  }, [items, searchQuery]);

  const activeGroup = useMemo(() => {
    return groups.find((g) => g.title === activeGroupTitle) || groups[0];
  }, [groups, activeGroupTitle]);

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

  return (
    <section className="grid gap-6 pb-24">
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

      {/* Global Config Settings Filter */}
      <div className="rounded-2xl border border-border-default bg-surface-1 p-4 shadow-sm">
        <span className="flex min-h-12 items-center gap-3 rounded-xl border border-border-default bg-surface-2 px-3 focus-within:border-accent">
          <MagnifyingGlassIcon className="h-4 w-4 text-foreground-muted shrink-0" />
          <input
            className="w-full bg-transparent text-sm text-foreground outline-none placeholder:text-foreground-subtle"
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search platform settings by key or label..."
            value={searchQuery}
          />
          {searchQuery && (
            <button
              onClick={() => setSearchQuery("")}
              className="text-xs font-semibold text-foreground-muted hover:text-foreground shrink-0 px-2 py-1 hover:bg-surface-3 rounded"
              type="button"
            >
              Clear
            </button>
          )}
        </span>
      </div>

      {searchQuery.trim() !== "" ? (
        <section className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
          <h3 className="font-heading text-lg font-bold text-foreground border-b border-border-default/45 pb-3">
            Search Results ({filteredKeys.length})
          </h3>
          {filteredKeys.length === 0 ? (
            <p className="mt-4 text-sm text-foreground-muted">
              No platform settings matched your search query.
            </p>
          ) : (
            <div className="mt-5 grid gap-5 sm:grid-cols-2">
              {filteredKeys.map((item) => {
                const key = item.key as ConfigKey;
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
          )}
        </section>
      ) : (
        <div className="grid gap-6 md:grid-cols-[240px_1fr]">
          {/* Settings Group Navigation Sidebar - Desktop only */}
          <aside className="hidden md:block">
            <nav className="flex flex-col gap-1.5 rounded-2xl border border-border-default bg-surface-1 p-4 shadow-sm h-fit">
              <p className="px-2 text-xs font-semibold uppercase tracking-[0.05em] text-foreground-muted mb-2">
                Setting Domains
              </p>
              {groups.map((group) => {
                const isActive = group.title === activeGroupTitle;
                const changesInGroup = group.keys.filter(
                  (key) => drafts[key] !== itemsByKey.get(key)?.value,
                ).length;
                return (
                  <button
                    key={group.title}
                    onClick={() => setActiveGroupTitle(group.title)}
                    className={[
                      "flex items-center justify-between min-h-11 rounded-xl px-4 py-2 text-sm font-semibold transition-all outline-none focus-visible:ring-2 focus-visible:ring-accent text-left",
                      isActive
                        ? "bg-foreground text-background shadow-sm"
                        : "text-foreground-muted hover:bg-surface-2 hover:text-foreground",
                    ].join(" ")}
                    type="button"
                  >
                    <span>{group.title}</span>
                    {changesInGroup > 0 ? (
                      <span
                        className={[
                          "rounded-full px-1.5 py-0.5 text-[10px] font-bold",
                          isActive
                            ? "bg-accent text-white"
                            : "bg-accent/10 text-accent",
                        ].join(" ")}
                      >
                        +{changesInGroup}
                      </span>
                    ) : null}
                  </button>
                );
              })}
            </nav>
          </aside>

          {/* Horizontal scroll tabs navigation - Mobile only */}
          <div className="md:hidden">
            <div className="flex gap-2 overflow-x-auto pb-2 scrollbar-none">
              {groups.map((group) => {
                const isActive = group.title === activeGroupTitle;
                const changesInGroup = group.keys.filter(
                  (key) => drafts[key] !== itemsByKey.get(key)?.value,
                ).length;
                return (
                  <button
                    key={group.title}
                    onClick={() => setActiveGroupTitle(group.title)}
                    className={[
                      "shrink-0 flex items-center gap-1.5 px-4 py-2.5 text-xs font-semibold rounded-xl transition border",
                      isActive
                        ? "bg-foreground text-background border-transparent"
                        : "text-foreground-muted bg-surface-1 border-border-default hover:bg-surface-2",
                    ].join(" ")}
                    type="button"
                  >
                    <span>{group.title}</span>
                    {changesInGroup > 0 ? (
                      <span className="w-1.5 h-1.5 rounded-full bg-accent" />
                    ) : null}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Active Settings Group inputs grid */}
          <div className="min-w-0">
            {activeGroup ? (
              <section className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
                <h3 className="font-heading text-lg font-bold text-foreground border-b border-border-default/45 pb-3">
                  {activeGroup.title}
                </h3>
                <div className="mt-5 grid gap-5 sm:grid-cols-2">
                  {activeGroup.keys.map((key) => {
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
            ) : null}
          </div>
        </div>
      )}

      {/* Floating Save Action Bar - Animates up when dirty drafts are present */}
      {isSuperadmin && (
        <div
          className={[
            "fixed bottom-6 left-1/2 -translate-x-1/2 z-40 w-[calc(100%-2rem)] max-w-xl rounded-2xl border border-border-default bg-surface-2 p-4 shadow-bento transition-all duration-300 ease-in-out flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3",
            changedKeys.length > 0
              ? "transform translate-y-0 opacity-100 scale-100"
              : "transform translate-y-12 opacity-0 scale-95 pointer-events-none",
          ].join(" ")}
        >
          <div className="flex items-center gap-3">
            <span className="flex h-2.5 w-2.5 shrink-0 rounded-full bg-accent animate-pulse" />
            <div>
              <p className="text-sm font-semibold text-foreground">
                {changedKeys.length} unsaved change{changedKeys.length === 1 ? "" : "s"}
              </p>
              <p className="text-xs text-foreground-muted">
                {tooManyChanges
                  ? `Save limit exceeded (max ${MAX_UPDATES_PER_SAVE})`
                  : "MFA signature verification required"}
              </p>
            </div>
          </div>
          <div className="flex items-center justify-end gap-2.5">
            <button
              onClick={() => {
                if (items) {
                  setDrafts(
                    Object.fromEntries(
                      items.map((item) => [item.key, item.value]),
                    ),
                  );
                }
                setError(null);
                setNotice(null);
              }}
              className="min-h-11 px-4 py-2 text-xs font-semibold rounded-xl transition border border-border-default bg-surface-1 hover:bg-surface-3 text-foreground"
              type="button"
            >
              Discard
            </button>
            <Button
              disabled={tooManyChanges}
              onClick={() => setIsConfirmOpen(true)}
              className="min-h-11 px-4 py-2 text-xs font-semibold"
            >
              Review & Save
            </Button>
          </div>
        </div>
      )}

      {/* Verification & Audit Modal */}
      {isSuperadmin && isConfirmOpen && (
        <div
          className="fixed inset-0 z-50 grid place-items-center bg-black/50 p-0 sm:p-4 animate-[fade-in_120ms_ease-out]"
          role="dialog"
          aria-modal="true"
        >
          <div
            className="w-full h-full sm:h-auto sm:max-w-lg rounded-t-2xl sm:rounded-2xl border border-border-default bg-surface-1 p-6 shadow-bento flex flex-col gap-4 overflow-y-auto"
            onClick={(e) => e.stopPropagation()}
          >
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
                Super-Admin Audit Confirmation
              </p>
              <h2 className="mt-1 font-heading text-xl font-bold text-foreground">
                Review Configuration Changes
              </h2>
              <p className="mt-1.5 text-xs text-foreground-muted">
                Please verify the modified constants before entering your MFA token.
              </p>
            </div>

            {/* Config Diffs comparison layout */}
            <div className="rounded-xl border border-border-default bg-surface-2 p-3.5 max-h-48 overflow-y-auto text-xs space-y-2">
              <div className="grid grid-cols-3 font-semibold text-foreground-muted pb-1.5 border-b border-border-default/45">
                <span className="col-span-1">Variable</span>
                <span className="col-span-1 text-right">Current</span>
                <span className="col-span-1 text-right">Draft</span>
              </div>
              {changedKeys.map((key) => {
                const original = itemsByKey.get(key)?.value;
                const draft = drafts[key];
                return (
                  <div
                    key={key}
                    className="grid grid-cols-3 gap-2 py-1 border-b border-border-default/45 last:border-0 last:pb-0 font-mono"
                  >
                    <span
                      className="col-span-1 text-foreground font-semibold break-all truncate font-heading"
                      title={key}
                    >
                      {labelForKey(key)}
                    </span>
                    <span className="col-span-1 text-foreground-muted text-right line-through break-all">
                      {original}
                    </span>
                    <span className="col-span-1 text-accent font-bold text-right break-all">
                      {draft}
                    </span>
                  </div>
                );
              })}
            </div>

            {/* Required Audit Reason field */}
            <label className="grid gap-2 text-sm font-semibold text-foreground">
              Reason for change (audit trail)
              <input
                className="min-h-12 rounded-xl border border-border-default bg-background px-4 text-sm font-normal text-foreground outline-none transition-colors focus-visible:ring-2 focus-visible:ring-accent"
                onChange={(event) => setReason(event.target.value)}
                placeholder="Why are you making these changes?"
                value={reason}
                required
              />
            </label>

            {/* TOTP Validation field */}
            <TotpInput onChange={setTotpCode} value={totpCode} />

            {/* Modal actions row */}
            <div className="mt-2 flex flex-col-reverse gap-2.5 sm:flex-row sm:justify-end border-t border-border-default/45 pt-4">
              <button
                className="min-h-12 rounded-xl border border-border-default px-5 py-2 text-sm font-semibold text-foreground transition hover:bg-surface-2"
                onClick={() => {
                  setIsConfirmOpen(false);
                  setReason("");
                  setTotpCode("");
                }}
                type="button"
                disabled={pending}
              >
                Cancel
              </button>
              <Button
                disabled={!canSave}
                onClick={async () => {
                  await handleSave();
                  setIsConfirmOpen(false);
                }}
                className="min-h-12 px-5 py-2 text-sm font-semibold"
              >
                {pending ? "Saving..." : "Confirm & Save"}
              </Button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
