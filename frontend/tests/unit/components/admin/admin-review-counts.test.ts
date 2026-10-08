/**
 * Admin review-queue badge coverage tests.
 *
 * Six admin pages fanned out "needs review" notifications to admins while
 * showing no nav counter, because the badge map was hand-maintained and had
 * drifted. These pin the queue list so adding a review surface without its
 * badge fails here rather than in QA.
 */
import { describe, expect, it, vi } from "vitest";

import { ADMIN_REVIEW_QUEUES } from "@/components/modules/admin/admin-review-counts";
import * as sdk from "@/lib/generated/sdk.gen";

vi.mock("@/lib/generated/sdk.gen", { spy: true });

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
      "/admin/users",
    ]);
  });

  it("gives every queue a loader", () => {
    for (const queue of ADMIN_REVIEW_QUEUES) {
      expect(typeof queue.load).toBe("function");
    }
  });

  it("counts only the users actually waiting on identity review", async () => {
    // Not every user: an unfiltered total would light the badge permanently
    // and stop meaning anything, the way the payouts badge did on one old
    // terminal failure.
    const queue = ADMIN_REVIEW_QUEUES.find(
      (candidate) => candidate.href === "/admin/users",
    );
    const listUsers = vi
      .spyOn(sdk, "listAdminUsersV1AdminUsersGet")
      .mockResolvedValue({
        response: { ok: true },
        data: { total: 3, items: [], page: 1, page_size: 1 },
      } as never);

    const count = await queue!.load({ Authorization: "Bearer test" });

    expect(count).toBe(3);
    expect(listUsers.mock.calls[0][0]).toMatchObject({
      query: { status: "kyc_pending" },
    });
  });

  it("addresses each queue at a distinct href", () => {
    const hrefs = ADMIN_REVIEW_QUEUES.map((queue) => queue.href);
    expect(new Set(hrefs).size).toBe(hrefs.length);
  });
});
