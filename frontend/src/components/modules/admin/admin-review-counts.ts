/**
 * Admin review-queue badge counts.
 *
 * Every queue that fans out an "item awaiting admin review" notification needs
 * a matching nav counter, or an admin is told to look at something the nav
 * gives no sign of. The map used to be four hand-written entries against
 * fourteen notifying domains, so Developer, Credentials, GDPR, Moderation and
 * Payouts notified silently — QA found Developer, and it was one of five.
 *
 * Each loader resolves to a count and never throws: this drives a badge on a
 * shell wrapping every admin route, so a failure in one queue must not take
 * down a page about something else. A failed load reads as zero.
 *
 * Mirrors `_DOMAIN_TITLES` in `backend/app/modules/admin/notifications.py`.
 * `/admin/money` is deliberately absent: refund intents notify admins, but no
 * endpoint exposes "refunds needing attention", so there is nothing to count
 * yet. Adding one is a backend change, not a key in this list.
 */
import {
  adminListOrgsV1AdminOrgsGet,
  listAdminAttestationDisputes,
  listAdminAttestations,
  listAdminDeletionRequestsV1AdminGdprDeletionRequestsGet,
  listAdminPayoutsV1AdminPayoutsGet,
  listAdminProjectDisputes,
  listCredentialReviewQueueV1AdminCredentialsGet,
  listDeveloperApplicationsForAdminV1AdminDeveloperApplicationsGet,
  listModerationQueueV1AdminModerationQueueGet,
  listOrgAttestorApplicationsForAdmin,
} from "@/lib/generated/sdk.gen";

/** One admin nav destination and how to count what is waiting there. */
export type AdminReviewQueue = {
  /** Nav href the badge attaches to. */
  href: string;
  /**
   * Resolve the number of items needing attention.
   *
   * @param headers - Authorization headers for the admin session.
   */
  load: (headers: Record<string, string>) => Promise<number>;
};

/** A paged admin response, where the server's total beats counting a page. */
type PagedTotal = { total: number };

/** Read `total` from a paged response, or 0 if the request did not succeed. */
function totalOf(result: {
  response: { ok: boolean };
  data?: PagedTotal;
}): number {
  return result.response.ok && result.data ? result.data.total : 0;
}

export const ADMIN_REVIEW_QUEUES: AdminReviewQueue[] = [
  {
    href: "/admin/attestations",
    load: async (headers) => {
      const result = await listAdminAttestations({
        headers,
        query: { status: "needs_admin" },
      });
      return result.response.ok && result.data
        ? result.data.attestations.length
        : 0;
    },
  },
  {
    href: "/admin/attestors",
    load: async (headers) => {
      const result = await listOrgAttestorApplicationsForAdmin({
        headers,
        query: { status: "submitted" },
      });
      return result.response.ok && result.data
        ? result.data.applications.length
        : 0;
    },
  },
  {
    href: "/admin/credentials",
    load: async (headers) => {
      const result = await listCredentialReviewQueueV1AdminCredentialsGet({
        headers,
        query: { status: "pending" },
      });
      return result.response.ok && result.data
        ? result.data.credentials.length
        : 0;
    },
  },
  {
    href: "/admin/developer",
    load: async (headers) => {
      const result =
        await listDeveloperApplicationsForAdminV1AdminDeveloperApplicationsGet({
          headers,
          query: { status: "pending" },
        });
      return result.response.ok && result.data
        ? result.data.applications.length
        : 0;
    },
  },
  {
    href: "/admin/disputes",
    load: async (headers) => {
      // Two independent queues share one page, so the badge is their sum.
      const [attestation, project] = await Promise.all([
        listAdminAttestationDisputes({ headers, query: { status: "active" } }),
        listAdminProjectDisputes({ headers }),
      ]);
      const attestationOpen =
        attestation.response.ok && attestation.data
          ? attestation.data.disputes.length
          : 0;
      const projectOpen =
        project.response.ok && project.data
          ? project.data.disputes.filter(
              (dispute: { status: string }) => dispute.status !== "resolved",
            ).length
          : 0;
      return attestationOpen + projectOpen;
    },
  },
  {
    href: "/admin/gdpr",
    load: async (headers) => {
      const result =
        await listAdminDeletionRequestsV1AdminGdprDeletionRequestsGet({
          headers,
          query: { status: "pending", page: 1, page_size: 1 },
        });
      return totalOf(result);
    },
  },
  {
    href: "/admin/moderation",
    load: async (headers) => {
      const result = await listModerationQueueV1AdminModerationQueueGet({
        headers,
        query: { page: 1, page_size: 1 },
      });
      return totalOf(result);
    },
  },
  {
    href: "/admin/organizations",
    load: async (headers) => {
      const result = await adminListOrgsV1AdminOrgsGet({
        headers,
        query: { kyb_status: "pending", page: 1, page_size: 1 },
      });
      return totalOf(result);
    },
  },
  {
    href: "/admin/payouts",
    load: async (headers) => {
      // Failed transfers are what the payout notifications are about: an OTP
      // hold, a stranded payout, a rejected transfer.
      const result = await listAdminPayoutsV1AdminPayoutsGet({
        headers,
        query: { status: "failed", page: 1, page_size: 1 },
      });
      return totalOf(result);
    },
  },
];

/**
 * Load every queue's count in parallel, keyed by nav href.
 *
 * One queue failing leaves that badge at zero and the rest intact.
 *
 * @param headers - Authorization headers for the admin session.
 */
export async function loadAdminReviewCounts(
  headers: Record<string, string>,
): Promise<Record<string, number>> {
  const entries = await Promise.all(
    ADMIN_REVIEW_QUEUES.map(async (queue) => {
      try {
        return [queue.href, await queue.load(headers)] as const;
      } catch {
        return [queue.href, 0] as const;
      }
    }),
  );
  return Object.fromEntries(entries);
}
