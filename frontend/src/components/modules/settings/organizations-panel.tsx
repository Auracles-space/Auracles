"use client";

/**
 * Organizations settings panel.
 *
 * Shows the authenticated user's organization memberships alongside pending
 * count of invitations addressed to their email. Accepting and declining live
 * on the organizations page inbox; this panel only points there.
 */
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import { listMyOrganizationsV1OrgsMineGet } from "@/lib/generated/sdk.gen";
import type { MyOrganizationResponse } from "@/lib/generated/types.gen";
import { loadReceivedInvitations } from "@/lib/organizations/received-invitations";
import { useRefetchOnFocus } from "@/lib/hooks/use-refetch-on-focus";

/**
 * Render organizations the user belongs to and invitations they can resolve.
 */
export function OrganizationsPanel() {
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [organizations, setOrganizations] = useState<MyOrganizationResponse[]>([]);
  const [invitationCount, setInvitationCount] = useState(0);

  useEffect(() => {
    let mounted = true;

    async function loadData(): Promise<void> {
      configureBrowserClient();
      const [organizationsResult, invitationsData] = await Promise.all([
        listMyOrganizationsV1OrgsMineGet({ headers: getAccessTokenHeaders() }),
        loadReceivedInvitations(),
      ]);

      if (!mounted) {
        return;
      }

      setLoading(false);
      if (
        !organizationsResult.response.ok ||
        !organizationsResult.data ||
        invitationsData === null
      ) {
        setError(
          organizationsResult.data
            ? "We could not load your invitations. Try again."
            : describeGeneratedError(organizationsResult.error),
        );
        return;
      }

      setError(null);
      setOrganizations(organizationsResult.data.organizations);
      setInvitationCount(invitationsData.length);
    }

    void loadData();
    return () => {
      mounted = false;
    };
  }, []);

  // Refresh org offer dots when the user returns to the tab (orgs only; the
  // invitation list is cached and refreshed on its own actions).
  const refreshOrganizations = useCallback(async () => {
    configureBrowserClient();
    const res = await listMyOrganizationsV1OrgsMineGet({
      headers: getAccessTokenHeaders(),
    });
    if (res.response.ok && res.data) {
      setOrganizations(res.data.organizations);
    }
  }, []);
  useRefetchOnFocus(refreshOrganizations);


  return (
    <div className="grid gap-6">
      {error ? (
        <p
          className="rounded-xl border border-error/30 bg-error/10 p-3 text-sm text-error"
          role="alert"
        >
          {error}
        </p>
      ) : null}

      <section className="rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm md:p-6">
        <div className="mb-4 flex items-start justify-between gap-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
              Memberships
            </p>
            <h2 className="mt-2 font-heading text-2xl font-bold text-foreground">
              My organizations
            </h2>
          </div>
        </div>

        {loading ? (
          <p className="text-sm text-foreground-muted">Loading organizations...</p>
        ) : organizations.length === 0 ? (
          <p className="rounded-xl border border-border-default bg-surface-2 p-4 text-sm text-foreground-muted">
            You have not joined any organizations yet.
          </p>
        ) : (
          <div className="grid gap-3">
            {organizations.map((item) => (
              <article
                className="rounded-xl border border-border-default bg-surface-2 p-4"
                key={item.org.id}
              >
                <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <h3 className="font-heading text-lg font-semibold text-foreground">
                        {item.org.name}
                      </h3>
                      {item.counts?.offers ? (
                        <span
                          aria-label={`${item.counts.offers} attestation offer${item.counts.offers === 1 ? "" : "s"} to review`}
                          className="h-2.5 w-2.5 shrink-0 rounded-full bg-accent"
                          title="Attestation offers to review"
                        />
                      ) : null}
                    </div>
                    <p className="mt-1 text-sm capitalize text-foreground-muted">
                      {item.role}
                    </p>
                  </div>
                  <Link
                    className="inline-flex min-h-12 items-center justify-center rounded-xl border border-border-default bg-background px-4 text-sm font-semibold text-foreground transition-colors hover:bg-surface-1"
                    href={`/dashboard/organizations/${item.org.id}`}
                  >
                    Open organization
                  </Link>
                </div>
              </article>
            ))}
          </div>
        )}
      </section>

      <section className="rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm md:p-6">
        <div className="mb-4">
          <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
            Invitations
          </p>
          <h2 className="mt-2 font-heading text-2xl font-bold text-foreground">
            Pending invitations
          </h2>
        </div>

        {loading ? (
          <p className="text-sm text-foreground-muted">Loading invitations...</p>
        ) : invitationCount === 0 ? (
          <p className="rounded-xl border border-border-default bg-surface-2 p-4 text-sm text-foreground-muted">
            No pending invitations.
          </p>
        ) : (
          <div className="flex flex-col gap-4 rounded-xl border border-accent/30 bg-surface-2 p-4 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-sm text-foreground">
              You have {invitationCount} pending invitation
              {invitationCount === 1 ? "" : "s"}. Accept or decline them from
              the Organizations page.
            </p>
            <Link
              className="inline-flex min-h-12 shrink-0 items-center justify-center rounded-xl bg-foreground px-5 text-sm font-semibold text-background transition hover:bg-foreground/90"
              href="/dashboard/organizations"
            >
              Review invitations
            </Link>
          </div>
        )}
      </section>
    </div>
  );
}
