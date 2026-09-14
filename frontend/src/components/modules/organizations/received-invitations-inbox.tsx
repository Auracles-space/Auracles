"use client";

/**
 * Invitation inbox shown at the top of the organizations list.
 *
 * Lists the organization invitations addressed to the signed-in user and lets
 * them accept or decline in place. Accepting routes into the organization.
 * Renders nothing when there is nothing to resolve, so the list page stays
 * clean for the common case; a failed load shows a single error line so a
 * pending invitation is never silently hidden.
 *
 * Maps to: docs/superpowers/specs/2026-09-13-org-onboarding-journey-design.md §2.
 */
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  configureBrowserClient,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import {
  acceptReceivedInvitation,
  declineReceivedInvitation,
} from "@/lib/generated/sdk.gen";
import type { MyInvitationResponse } from "@/lib/generated/types.gen";
import {
  invalidateReceivedInvitations,
  loadReceivedInvitations,
} from "@/lib/organizations/received-invitations";

type ReceivedInvitationsInboxProps = {
  /** Called after an invitation is accepted or declined, so the parent can refetch. */
  onResolved?: () => void;
};

/**
 * Render pending organization invitations with accept and decline actions.
 *
 * @param props - Optional callback fired once an invitation is resolved.
 */
export function ReceivedInvitationsInbox({ onResolved }: ReceivedInvitationsInboxProps) {
  const router = useRouter();
  const [invitations, setInvitations] = useState<MyInvitationResponse[]>([]);
  const [pending, setPending] = useState<{ id: string; action: "accept" | "decline" } | null>(
    null,
  );
  const [error, setError] = useState<string | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);

  const load = useCallback(async () => {
    try {
      const data = await loadReceivedInvitations();
      setInvitations(data ?? []);
      setLoadFailed(false);
    } catch {
      // A failed inbox load must never break the organizations page, but it
      // must say so: an invitation the user is waiting on could be behind it.
      setInvitations([]);
      setLoadFailed(true);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleAccept(invitation: MyInvitationResponse): Promise<void> {
    setPending({ id: invitation.id, action: "accept" });
    setError(null);
    configureBrowserClient();
    const result = await acceptReceivedInvitation({
      headers: getAccessTokenHeaders(),
      path: { invitation_id: invitation.id },
    });
    setPending(null);
    if (!result.response.ok) {
      setError("We could not accept this invitation. Try again.");
      return;
    }
    setInvitations((current) => current.filter((item) => item.id !== invitation.id));
    invalidateReceivedInvitations();
    onResolved?.();
    router.push(`/dashboard/organizations/${invitation.org.id}`);
  }

  async function handleDecline(invitationId: string): Promise<void> {
    setPending({ id: invitationId, action: "decline" });
    setError(null);
    configureBrowserClient();
    const result = await declineReceivedInvitation({
      headers: getAccessTokenHeaders(),
      path: { invitation_id: invitationId },
    });
    setPending(null);
    if (!result.response.ok) {
      setError("We could not decline this invitation. Try again.");
      return;
    }
    setInvitations((current) => current.filter((item) => item.id !== invitationId));
    invalidateReceivedInvitations();
    onResolved?.();
  }

  if (loadFailed) {
    return (
      <p className="mb-6 text-sm text-error" role="alert">
        We could not load your invitations. Refresh the page to try again.
      </p>
    );
  }

  if (invitations.length === 0) {
    return null;
  }

  return (
    <section
      aria-labelledby="received-invitations-heading"
      className="mb-8 rounded-2xl border border-accent/30 bg-surface-1 p-5 shadow-sm md:p-6"
    >
      <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
        Waiting on you
      </p>
      <h2
        className="mt-1 font-heading text-xl font-bold text-foreground"
        id="received-invitations-heading"
      >
        Invitations
      </h2>
      <p className="mt-1 text-sm text-foreground-muted">
        Accept to join the organization with the role offered, or decline to
        remove the invitation.
      </p>

      {error ? (
        <p className="mt-3 text-sm text-error" role="alert">
          {error}
        </p>
      ) : null}

      <ul className="mt-4 grid gap-3 md:grid-cols-2">
        {invitations.map((invitation) => {
          const rowBusy = pending?.id === invitation.id;
          return (
            <li
              className="flex flex-col gap-4 rounded-xl border border-border-default bg-surface-2 p-4"
              key={invitation.id}
            >
              <div>
                <h3 className="font-heading text-lg font-semibold text-foreground">
                  {invitation.org.name}
                </h3>
                <p className="mt-1 text-sm text-foreground-muted">
                  Role offered:{" "}
                  <span className="capitalize text-foreground">{invitation.role}</span>
                </p>
                <p className="mt-1 text-sm text-foreground-muted">
                  Invited by {invitation.invited_by_name ?? "an organization admin"}
                </p>
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                <Button
                  disabled={rowBusy}
                  loading={rowBusy && pending?.action === "accept"}
                  onClick={() => void handleAccept(invitation)}
                >
                  Accept
                </Button>
                <Button
                  className="w-full"
                  disabled={rowBusy}
                  loading={rowBusy && pending?.action === "decline"}
                  onClick={() => void handleDecline(invitation.id)}
                  variant="secondary"
                >
                  Decline
                </Button>
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
