/**
 * Admin review-queue badge coverage tests.
 *
 * Six admin pages fanned out "needs review" notifications to admins while
 * showing no nav counter, because the badge map was hand-maintained and had
 * drifted. These pin the queue list so adding a review surface without its
 * badge fails here rather than in QA.
 */
import { describe, expect, it } from "vitest";

import { ADMIN_REVIEW_QUEUES } from "@/components/modules/admin/admin-review-counts";

describe("ADMIN_REVIEW_QUEUES", () => {
  it("covers every admin page that receives review notifications", () => {
    // Mirrors _DOMAIN_TITLES in backend/app/modules/admin/notifications.py,
    // minus /admin/money: no endpoint exposes refunds needing attention, so
    // it has no countable source yet.
    expect(ADMIN_REVIEW_QUEUES.map((queue) => queue.href).sort()).toEqual([
      "/admin/attestations",
      "/admin/attestors",
      "/admin/credentials",
      "/admin/developer",
      "/admin/disputes",
      "/admin/gdpr",
      "/admin/moderation",
      "/admin/organizations",
      "/admin/payouts",
    ]);
  });

  it("gives every queue a loader", () => {
    for (const queue of ADMIN_REVIEW_QUEUES) {
      expect(typeof queue.load).toBe("function");
    }
  });

  it("addresses each queue at a distinct href", () => {
    const hrefs = ADMIN_REVIEW_QUEUES.map((queue) => queue.href);
    expect(new Set(hrefs).size).toBe(hrefs.length);
  });
});
