/**
 * Canonical public origin for crawler-facing files.
 *
 * `robots.txt` and `sitemap.xml` must name absolute URLs, and they must name
 * the origin a visitor actually reaches — the apex, not the Amplify build URL
 * and not the API host. There is no existing env var for it, so the apex is
 * the default and `NEXT_PUBLIC_SITE_URL` overrides it for a preview or a
 * rename. That keeps this zero-config in production while leaving a way out
 * that does not need a Terraform apply.
 */

/** The apex the production domain association points at. */
const DEFAULT_SITE_URL = "https://auracles.space";

/**
 * Resolve the public origin, with no trailing slash.
 *
 * @returns Absolute origin such as `https://auracles.space`.
 */
export function siteUrl(): string {
  const configured = process.env.NEXT_PUBLIC_SITE_URL?.trim();
  const resolved =
    configured && configured.length > 0 ? configured : DEFAULT_SITE_URL;
  return resolved.replace(/\/+$/, "");
}
