"use client";

/**
 * Pending invitations toast announcer.
 *
 * Fetches token-free received invitations on authenticated shell mount and
 * surfaces a one-time toast when the invitation id set changes.
 */
import { usePathname } from "next/navigation";
import { useEffect } from "react";

import { useToast } from "@/components/ui/toast";
import { loadReceivedInvitations } from "@/lib/organizations/received-invitations";

const PENDING_INVITES_SEEN_KEY = "pending-invites-seen";

/**
 * Announce pending invitations once per unique invitation-id set.
 */
export function PendingInvitationsToast() {
  const toast = useToast();
  const pathname = usePathname();
  // The organizations page renders the inbox itself; a toast pointing the
  // user at the page they are already on would be noise.
  const onInboxPage = pathname?.startsWith("/dashboard/organizations") ?? false;

  useEffect(() => {
    if (onInboxPage) {
      return;
    }
    let mounted = true;

    async function loadPendingInvitations(): Promise<void> {
      try {
        const invitations = await loadReceivedInvitations();

        if (!mounted || invitations === null) {
          return;
        }

        const invitationIds = invitations.map((invitation) => invitation.id).sort();
        if (invitationIds.length === 0) {
          return;
        }

        const key = invitationIds.join(",");
        if (localStorage.getItem(PENDING_INVITES_SEEN_KEY) === key) {
          return;
        }

        const count = invitationIds.length;
        toast.success(
          `You have ${count} pending invitation${
            count === 1 ? "" : "s"
          } — review them on the Organizations page.`,
        );
        localStorage.setItem(PENDING_INVITES_SEEN_KEY, key);
      } catch {
        // Discoverability is best-effort; a transient fetch failure should not
        // block the authenticated shell or surface noise on page load.
      }
    }

    void loadPendingInvitations();
    return () => {
      mounted = false;
    };
  }, [toast, onInboxPage]);

  return null;
}
