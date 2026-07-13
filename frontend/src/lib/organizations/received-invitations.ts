/**
 * Shared loader for the authenticated user's received org invitations.
 *
 * Three consumers can mount at once on the settings/organizations page — the
 * global toast (app shell), the settings-nav count badge, and the inbox panel.
 * This collapses their concurrent calls into a single request via in-flight
 * deduplication plus a short TTL cache, and lets a mutation invalidate the
 * cache so the ambient consumers refresh on their next mount.
 */
import {
  configureBrowserClient,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import { listReceivedInvitations } from "@/lib/generated/sdk.gen";
import type { MyInvitationResponse } from "@/lib/generated/types.gen";

const TTL_MS = 5000;

let cache: { at: number; data: MyInvitationResponse[] } | null = null;
let inFlight: Promise<MyInvitationResponse[] | null> | null = null;

/**
 * Load received invitations, sharing one request across concurrent callers.
 *
 * @returns The pending invitations, or null when the request failed.
 */
export async function loadReceivedInvitations(): Promise<
  MyInvitationResponse[] | null
> {
  if (cache && Date.now() - cache.at < TTL_MS) {
    return cache.data;
  }
  if (inFlight) {
    return inFlight;
  }

  inFlight = (async () => {
    try {
      configureBrowserClient();
      const result = await listReceivedInvitations({
        headers: getAccessTokenHeaders(),
      });
      if (!result.response.ok || !result.data) {
        return null;
      }
      cache = { at: Date.now(), data: result.data.invitations };
      return cache.data;
    } finally {
      inFlight = null;
    }
  })();

  return inFlight;
}

/** Drop the cache so the next load refetches (call after accept/decline). */
export function invalidateReceivedInvitations(): void {
  cache = null;
}
