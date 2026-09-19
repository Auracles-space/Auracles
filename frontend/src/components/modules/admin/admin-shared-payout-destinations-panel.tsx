"use client";

/**
 * Admin review queue for bank accounts paid to more than one owner.
 *
 * Sharing a payout destination is allowed and usually innocent — a sole
 * trader's personal payout account and their company's are routinely the same
 * account. What matters is that it is visible: one account collecting for many
 * separate identities is the shape of a payout funnel, and it is the only
 * signal of that the platform holds. The alternative the platform used to have
 * — refusing the second owner outright — discarded the signal along with the
 * sole traders it wrongly blocked.
 *
 * Registration is refused past a small ceiling so a human looks. This is where
 * they look, and where they can say yes: a group of related trading entities
 * paying into one treasury account is legitimate and would otherwise be stuck.
 *
 * Maps to: FR-FIN-* (payout oversight).
 */

import { useCallback, useEffect, useState } from "react";

import {
  listSharedPayoutDestinations,
  setPayoutDestinationAllowance,
} from "@/lib/generated/sdk.gen";
import type { AdminSharedPayoutDestination } from "@/lib/generated/types.gen";
import { Button } from "@/components/ui/button";
import { TableSkeleton } from "@/components/ui/skeletons/table-skeleton";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";

/**
 * Render shared payout destinations and the control that raises their ceiling.
 */
export function AdminSharedPayoutDestinationsPanel() {
  const [destinations, setDestinations] = useState<
    AdminSharedPayoutDestination[]
  >([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // Lookup hash of the destination whose allowance is being edited.
  const [editing, setEditing] = useState<string | null>(null);
  const [maxOwners, setMaxOwners] = useState("");
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    configureBrowserClient();
    const result = await listSharedPayoutDestinations({
      headers: getAccessTokenHeaders(),
    });
    if (result.error || !result.data) {
      setError(describeGeneratedError(result.error));
      setLoading(false);
      return;
    }
    setDestinations(result.data.destinations);
    setLoading(false);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const saveAllowance = useCallback(
    async (destination: AdminSharedPayoutDestination) => {
      setSaving(true);
      setError(null);
      configureBrowserClient();
      const result = await setPayoutDestinationAllowance({
        headers: getAccessTokenHeaders(),
        body: {
          provider: destination.provider,
          lookup_hash: destination.lookup_hash,
          max_owners: Number(maxOwners),
          note,
        },
      });
      setSaving(false);
      if (result.error || !result.data) {
        setError(describeGeneratedError(result.error));
        return;
      }
      setEditing(null);
      setNote("");
      setMaxOwners("");
      await load();
    },
    [load, maxOwners, note],
  );

  if (loading) {
    return <TableSkeleton />;
  }

  return (
    <section className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
      <h2 className="font-heading text-xl font-bold text-foreground">
        Shared bank accounts
      </h2>
      <p className="mt-2 max-w-2xl text-sm leading-6 text-foreground-muted">
        Bank accounts that more than one person or organization is paid into.
        Sharing one is normal for a sole trader whose personal and company
        accounts are the same. Many separate owners behind a single account is
        worth a closer look.
      </p>

      {error ? (
        <p className="mt-4 text-sm text-error" role="alert">
          {error}
        </p>
      ) : null}

      {destinations.length === 0 ? (
        <p className="mt-5 text-sm text-foreground-muted">
          No bank account is shared by more than one owner.
        </p>
      ) : (
        <ul className="mt-5 grid gap-3">
          {destinations.map((destination) => (
            <li
              className="rounded-xl border border-border-default bg-surface-2 p-5"
              key={destination.lookup_hash}
            >
              <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                <div className="min-w-0">
                  <p className="font-heading text-base font-bold text-foreground">
                    {destination.provider_account_ref}
                  </p>
                  <p className="mt-1 text-xs uppercase tracking-[0.05em] text-foreground-muted">
                    {destination.provider}
                  </p>
                </div>
                <span className="shrink-0 rounded-badge border border-border-default bg-surface-1 px-2 py-1 text-xs font-semibold uppercase tracking-[0.05em] text-foreground-muted">
                  {destination.owner_count} of {destination.max_owners} owners
                </span>
              </div>

              <ul className="mt-4 grid gap-2">
                {destination.owners.map((owner) => (
                  <li
                    className="flex flex-wrap items-center gap-2 text-sm"
                    key={`${owner.kind}:${owner.id}`}
                  >
                    <span className="rounded-badge border border-border-default px-2 py-0.5 text-xs uppercase tracking-[0.05em] text-foreground-muted">
                      {owner.kind === "user" ? "Person" : "Organization"}
                    </span>
                    <span className="text-foreground">{owner.name}</span>
                  </li>
                ))}
              </ul>

              {editing === destination.lookup_hash ? (
                <div className="mt-5 grid gap-4 sm:max-w-md">
                  <div>
                    <label
                      className="mb-1 block text-sm font-semibold text-foreground"
                      htmlFor={`max-owners-${destination.lookup_hash}`}
                    >
                      Owners allowed
                    </label>
                    <input
                      className="flex min-h-12 w-full rounded-xl border border-border-default bg-background px-3 text-sm text-foreground outline-none focus-visible:ring-2 focus-visible:ring-accent"
                      id={`max-owners-${destination.lookup_hash}`}
                      inputMode="numeric"
                      onChange={(event) =>
                        setMaxOwners(event.target.value.replace(/\D/g, ""))
                      }
                      value={maxOwners}
                    />
                  </div>
                  <div>
                    <label
                      className="mb-1 block text-sm font-semibold text-foreground"
                      htmlFor={`note-${destination.lookup_hash}`}
                    >
                      Why this is allowed
                    </label>
                    <textarea
                      className="w-full rounded-xl border border-border-default bg-background p-3 text-sm text-foreground outline-none focus-visible:ring-2 focus-visible:ring-accent"
                      id={`note-${destination.lookup_hash}`}
                      onChange={(event) => setNote(event.target.value)}
                      rows={3}
                      value={note}
                    />
                    <p className="mt-1 text-xs text-foreground-muted">
                      Recorded with your name, so whoever reviews this next can
                      see the reasoning.
                    </p>
                  </div>
                  <div className="flex flex-wrap gap-3">
                    <Button
                      disabled={saving || maxOwners === ""}
                      loading={saving}
                      onClick={() => saveAllowance(destination)}
                      type="button"
                    >
                      Save allowance
                    </Button>
                    <Button
                      disabled={saving}
                      onClick={() => setEditing(null)}
                      type="button"
                      variant="secondary"
                    >
                      Cancel
                    </Button>
                  </div>
                </div>
              ) : (
                <Button
                  className="mt-5"
                  onClick={() => {
                    setEditing(destination.lookup_hash);
                    setMaxOwners(String(destination.max_owners));
                    setNote("");
                  }}
                  type="button"
                  variant="secondary"
                >
                  Allow more owners
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
