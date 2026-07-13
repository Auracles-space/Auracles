"use client";

/**
 * Organizations settings panel.
 *
 * Shows the authenticated user's organization memberships alongside pending
 * invitations addressed to their email. Accept and decline actions use the
 * token-free received-invitations endpoints.
 */
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import {
  acceptReceivedInvitation,
  declineReceivedInvitation,
  listMyOrganizationsV1OrgsMineGet,
  listReceivedInvitations,
} from "@/lib/generated/sdk.gen";
import type {
  MyInvitationResponse,
  MyOrganizationResponse,
} from "@/lib/generated/types.gen";

/**
 * Render organizations the user belongs to and invitations they can resolve.
 */
export function OrganizationsPanel() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [organizations, setOrganizations] = useState<MyOrganizationResponse[]>([]);
  const [invitations, setInvitations] = useState<MyInvitationResponse[]>([]);
  const [pendingInvitationId, setPendingInvitationId] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;

    async function loadData(): Promise<void> {
      configureBrowserClient();
      const headers = getAccessTokenHeaders();
      const [organizationsResult, invitationsResult] = await Promise.all([
        listMyOrganizationsV1OrgsMineGet({ headers }),
        listReceivedInvitations({ headers }),
      ]);

      if (!mounted) {
        return;
      }

      setLoading(false);
      if (
        !organizationsResult.response.ok ||
        !organizationsResult.data ||
        !invitationsResult.response.ok ||
        !invitationsResult.data
      ) {
        setError(
          describeGeneratedError(
            organizationsResult.error ?? invitationsResult.error,
          ),
        );
        return;
      }

      setError(null);
      setOrganizations(organizationsResult.data.organizations);
      setInvitations(invitationsResult.data.invitations);
    }

    void loadData();
    return () => {
      mounted = false;
    };
  }, []);

  async function handleAccept(invitation: MyInvitationResponse): Promise<void> {
    setPendingInvitationId(invitation.id);
    configureBrowserClient();
    const result = await acceptReceivedInvitation({
      headers: getAccessTokenHeaders(),
      path: { invitation_id: invitation.id },
    });
    setPendingInvitationId(null);

    if (!result.response.ok || !result.data) {
      setError(describeGeneratedError(result.error));
      return;
    }

    setInvitations((current) => current.filter((item) => item.id !== invitation.id));
    router.refresh();
    router.push(`/dashboard/organizations/${invitation.org.id}`);
  }

  async function handleDecline(invitationId: string): Promise<void> {
    setPendingInvitationId(invitationId);
    configureBrowserClient();
    const result = await declineReceivedInvitation({
      headers: getAccessTokenHeaders(),
      path: { invitation_id: invitationId },
    });
    setPendingInvitationId(null);

    if (!result.response.ok) {
      setError(describeGeneratedError(result.error));
      return;
    }

    setInvitations((current) => current.filter((item) => item.id !== invitationId));
  }

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
                    <h3 className="font-heading text-lg font-semibold text-foreground">
                      {item.org.name}
                    </h3>
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
        ) : invitations.length === 0 ? (
          <p className="rounded-xl border border-border-default bg-surface-2 p-4 text-sm text-foreground-muted">
            No pending invitations.
          </p>
        ) : (
          <div className="grid gap-3">
            {invitations.map((invitation) => {
              const busy = pendingInvitationId === invitation.id;
              return (
                <article
                  className="rounded-xl border border-border-default bg-surface-2 p-4"
                  key={invitation.id}
                >
                  <div className="flex flex-col gap-4">
                    <div>
                      <h3 className="font-heading text-lg font-semibold text-foreground">
                        {invitation.org.name}
                      </h3>
                      <p className="mt-1 text-sm text-foreground-muted">
                        Role offered:{" "}
                        <span className="capitalize text-foreground">
                          {invitation.role}
                        </span>
                      </p>
                      <p className="mt-1 text-sm text-foreground-muted">
                        Invited by {invitation.invited_by_name ?? "An organization admin"}
                      </p>
                    </div>

                    <div className="grid gap-3 sm:grid-cols-2">
                      <Button
                        loading={busy}
                        onClick={() => void handleAccept(invitation)}
                      >
                        Accept
                      </Button>
                      <Button
                        className="w-full"
                        loading={busy}
                        onClick={() => void handleDecline(invitation.id)}
                        variant="secondary"
                      >
                        Decline
                      </Button>
                    </div>
                  </div>
                </article>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}
