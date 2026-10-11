/**
 * robots.txt policy tests.
 *
 * The file is small and its mistakes are expensive: an over-broad Allow
 * invited GPTBot to enumerate `/explore`'s filter facets on 2026-10-11, which
 * drained the API's rate-limit bucket and showed real visitors "Catalog is
 * temporarily unavailable". These pin the three things it has to get right.
 */
import { describe, expect, it } from "vitest";

import robots from "@/app/robots";

/** The single rule block this policy produces. */
function rule() {
  const rules = robots().rules;
  return Array.isArray(rules) ? rules[0] : rules;
}

/** Disallow entries as a flat array of strings. */
function disallowed(): string[] {
  const value = rule().disallow;
  if (value === undefined) {
    return [];
  }
  return Array.isArray(value) ? value : [value];
}

describe("robots.txt", () => {
  it("keeps the pages built SSR for indexing crawlable", () => {
    // /explore and /explore/<id> are the acquisition surface; blocking them
    // would discard the reason those pages are server-rendered at all.
    expect(rule().allow).toBe("/");
    expect(disallowed()).not.toContain("/explore");
  });

  it("closes the faceted filter space", () => {
    // Thirteen filters plus paging and sorting is an unbounded URL space, and
    // every combination is a cache miss costing a render and a catalog query.
    expect(disallowed()).toContain("/explore?*");
  });

  it("hides routes whose URL is itself the credential", () => {
    // Not merely private: an indexed invitation or reset link is a leak.
    for (const path of [
      "/org-invitations",
      "/reset-password",
      "/verify-email",
    ]) {
      expect(disallowed()).toContain(path);
    }
  });

  it("hides the auth-gated areas", () => {
    for (const path of ["/admin", "/dashboard", "/settings", "/api"]) {
      expect(disallowed()).toContain(path);
    }
  });

  it("points at an absolute sitemap on the public origin", () => {
    expect(robots().sitemap).toBe("https://auracles.space/sitemap.xml");
  });
});
