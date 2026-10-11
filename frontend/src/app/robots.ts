/**
 * robots.txt for the public site.
 *
 * It was absent entirely, so `/robots.txt` returned the app's 404 page. That
 * is what an external verification scan flagged: a crawler asking the
 * conventional question got an HTML error document instead of an answer.
 *
 * Policy (human decision 2026-10-11): public pages are crawlable, because
 * `/explore` and framework detail pages are rendered SSR specifically to be
 * indexed. Everything behind auth is disallowed — crawling it only burns
 * budget on redirects and can surface dashboard URLs in results.
 *
 * Token-bearing routes are disallowed on top of that, for a different reason:
 * an invitation, verification or reset link in a search index is a leaked
 * credential, not merely a wasted fetch.
 */
import type { MetadataRoute } from "next";

import { siteUrl } from "@/lib/site-url";

/**
 * Faceted filter URLs on Explore.
 *
 * `/explore` takes thirteen filters plus paging and sorting, so its
 * query-string space is effectively unbounded — and every distinct combination
 * is a fresh cache miss that costs a server render and a catalog query.
 * GPTBot enumerated it on 2026-10-11 at roughly 4.5 requests a second, drained
 * the API's public rate-limit bucket, and real visitors were shown "Catalog is
 * temporarily unavailable" on the marketplace page.
 *
 * `/explore` itself and every `/explore/<id>` detail page stay crawlable: they
 * are the pages rendered SSR to be indexed, and they are finite.
 */
const FACETED_FILTER_URLS = ["/explore?*"];

/** Auth-gated areas: nothing useful to a crawler behind any of them. */
const PRIVATE_AREAS = [
  "/admin",
  "/dashboard",
  "/settings",
  "/onboarding",
  "/api",
  "/profile/edit",
  "/profile/me",
];

/**
 * Routes whose URL carries a secret.
 *
 * These are not merely private — the path itself is the credential, so an
 * indexed copy hands it to anyone who finds it.
 */
const TOKEN_BEARING_ROUTES = [
  "/org-invitations",
  "/reset-password",
  "/verify-email",
];

/**
 * Build the robots.txt response.
 *
 * @returns Crawl rules plus the sitemap location.
 */
export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: "*",
        allow: "/",
        disallow: [
          ...FACETED_FILTER_URLS,
          ...PRIVATE_AREAS,
          ...TOKEN_BEARING_ROUTES,
        ],
      },
    ],
    sitemap: `${siteUrl()}/sitemap.xml`,
    host: siteUrl(),
  };
}
