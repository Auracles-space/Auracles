/**
 * sitemap.xml for the public site.
 *
 * Lists the static public pages and every published Framework, which are the
 * SSR pages that exist to be indexed. Auth-gated and token-bearing routes are
 * absent for the same reasons `robots.ts` disallows them.
 *
 * The Framework list is fetched at build time. That fetch is guarded: a
 * sitemap that throws would fail the Amplify build and take the whole
 * frontend release down over a file no visitor reads, so an unreachable API
 * degrades to the static entries instead.
 */
import type { MetadataRoute } from "next";

import { siteUrl } from "@/lib/site-url";

/**
 * Absolute backend origin for the build-time fetch.
 *
 * Read straight from the environment rather than through `resolveApiBaseUrl`,
 * which returns the relative `/api` proxy path whenever that is configured and
 * only falls back to the absolute origin for a server caller. That indirection
 * is right for components that run in both places; this file only ever runs on
 * the server, and getting a relative path here produced a sitemap with the
 * static pages and none of the Frameworks — silently, because the fetch guard
 * below treats any failure as "no frameworks".
 */
function backendOrigin(): string {
  return process.env.BACKEND_ORIGIN ?? "http://localhost:8000";
}

/**
 * Frameworks per request. The endpoint caps `page_size` at 100 and answers 422
 * above it — asking for 200 produced a sitemap with no Frameworks at all,
 * because the guard below cannot tell a rejected request from an empty one.
 */
const FRAMEWORK_PAGE_SIZE = 100;

/**
 * Most pages to walk, so a bad `total` cannot spin the build forever.
 * 20 pages is 2000 URLs, far beyond pilot scale and still a finite build.
 */
const MAX_FRAMEWORK_PAGES = 20;

/** Seconds before a built sitemap is considered stale. */
export const revalidate = 3600;

/** Public pages with no dynamic segment, most important first. */
const STATIC_PATHS = [
  { path: "/", priority: 1, changeFrequency: "daily" as const },
  { path: "/explore", priority: 0.9, changeFrequency: "daily" as const },
  { path: "/attestors", priority: 0.6, changeFrequency: "weekly" as const },
  { path: "/demand", priority: 0.5, changeFrequency: "weekly" as const },
  { path: "/terms", priority: 0.3, changeFrequency: "yearly" as const },
  { path: "/privacy", priority: 0.3, changeFrequency: "yearly" as const },
  { path: "/security", priority: 0.3, changeFrequency: "yearly" as const },
];

/** The fields this module needs from a published Framework row. */
type PublishedFramework = { id: string; updated_at?: string | null };

/**
 * Fetch every published Framework, walking the paginated endpoint.
 *
 * Degrades rather than throws, because a sitemap that throws fails the Amplify
 * build. It does say so on stderr first: an empty result and a refused request
 * look identical in the output, and that is how a 422 from an over-large
 * `page_size` shipped a Framework-less sitemap unnoticed.
 *
 * @returns Every published row, or as many as could be read.
 */
async function publishedFrameworks(): Promise<PublishedFramework[]> {
  const collected: PublishedFramework[] = [];
  try {
    for (let page = 1; page <= MAX_FRAMEWORK_PAGES; page += 1) {
      const response = await fetch(
        `${backendOrigin()}/v1/explore/frameworks` +
          `?page=${page}&page_size=${FRAMEWORK_PAGE_SIZE}`,
        { next: { revalidate } },
      );
      if (!response.ok) {
        console.warn(
          `sitemap: explore/frameworks page ${page} returned ` +
            `${response.status}; sitemap will be incomplete`,
        );
        break;
      }
      const body = (await response.json()) as {
        items?: unknown;
        total?: unknown;
      };
      const items = Array.isArray(body.items)
        ? (body.items as PublishedFramework[])
        : [];
      collected.push(...items);
      const total =
        typeof body.total === "number" ? body.total : collected.length;
      if (items.length === 0 || collected.length >= total) {
        break;
      }
    }
  } catch (caught) {
    console.warn(
      `sitemap: could not read explore/frameworks (${String(caught)}); ` +
        "sitemap will be incomplete",
    );
  }
  return collected;
}

/**
 * Build the sitemap.
 *
 * @returns Static public pages followed by published Framework detail pages.
 */
export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const origin = siteUrl();
  const now = new Date();

  const staticEntries = STATIC_PATHS.map((entry) => ({
    url: `${origin}${entry.path}`,
    lastModified: now,
    changeFrequency: entry.changeFrequency,
    priority: entry.priority,
  }));

  const frameworkEntries = (await publishedFrameworks()).map((framework) => ({
    url: `${origin}/explore/${framework.id}`,
    lastModified: framework.updated_at ? new Date(framework.updated_at) : now,
    changeFrequency: "weekly" as const,
    priority: 0.8,
  }));

  return [...staticEntries, ...frameworkEntries];
}
