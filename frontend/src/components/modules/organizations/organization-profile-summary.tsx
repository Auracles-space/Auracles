"use client";

/**
 * Read-only organization summary shown above the profile edit form.
 *
 * Surfaces what the owner most often needs to hand to someone else (the
 * public profile URL, with copy and open controls), the record dates
 * (created, verified), the member count, the country, and the caller's own
 * role. The slug and country live here rather than in the edit form because
 * each has its own owner-only dialog: the slug (Decision 5; the old address
 * keeps redirecting) and the country, which locks once business verification
 * is pending or verified since it picks the payout rail.
 *
 * Maps to: docs/superpowers/specs/2026-09-14-organizations-end-to-end-design.md §Slice B.
 */
import { useEffect, useState } from "react";
import { CheckIcon, CopyIcon, ExternalLinkIcon } from "@radix-ui/react-icons";

import { StatusPill } from "@/components/ui/status-pill";
import { PAYOUT_COUNTRIES } from "@/lib/marketplace/countries";
import { OrganizationCountryDialog } from "./organization-country-dialog";
import { useOrganization } from "./organization-context";
import { OrganizationSlugDialog } from "./organization-slug-dialog";

/** Format an ISO timestamp as a short readable date. */
function formatDate(value: string): string {
  return new Date(value).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

/** Verification states whose review is bound to the country (server rule). */
const COUNTRY_LOCKING_KYB = new Set(["pending", "verified"]);

/** Display name for an ISO country code, falling back to the code. */
function countryName(code: string): string {
  return PAYOUT_COUNTRIES.find((option) => option.code === code)?.name ?? code;
}

/**
 * Render the public URL row and the summary facts for the current org.
 */
export function OrganizationProfileSummary() {
  const { org, role, kybStatus, kybVerifiedAt, memberCount } = useOrganization();
  const [copied, setCopied] = useState(false);
  const [changingSlug, setChangingSlug] = useState(false);
  const [changingCountry, setChangingCountry] = useState(false);
  // window is only available after mount; the server render shows the path.
  const [origin, setOrigin] = useState("");
  useEffect(() => setOrigin(window.location.origin), []);

  const publicPath = `/orgs/${org.slug}`;
  const publicUrl = `${origin}${publicPath}`;

  async function copyUrl(): Promise<void> {
    try {
      await navigator.clipboard.writeText(publicUrl);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard access can be refused (insecure context, permissions); the
      // URL stays selectable on screen so nothing is lost.
      setCopied(false);
    }
  }

  const isVerified = kybStatus === "verified";
  const countryLocked = COUNTRY_LOCKING_KYB.has(kybStatus);

  return (
    <section className="flex flex-col gap-4 rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm sm:p-6">
      <div>
        <p className="text-xs font-semibold uppercase tracking-[0.05em] text-foreground-muted">
          Public profile
        </p>
        <div className="mt-2 flex flex-col gap-2 sm:flex-row sm:items-center">
          <code className="min-w-0 flex-1 select-all break-all rounded-xl border border-border-default bg-surface-2 px-3 py-2.5 text-sm text-foreground">
            {publicUrl}
          </code>
          <div className="flex flex-wrap gap-2">
            <button
              aria-label="Copy public profile URL"
              className="inline-flex min-h-11 min-w-11 items-center justify-center gap-1.5 rounded-xl border border-border-default bg-surface-1 px-3 text-sm font-semibold text-foreground transition hover:bg-surface-2"
              onClick={() => void copyUrl()}
              type="button"
            >
              {copied ? <CheckIcon className="h-4 w-4 text-success" /> : <CopyIcon className="h-4 w-4" />}
              <span>{copied ? "Copied" : "Copy"}</span>
            </button>
            <a
              aria-label="Open public profile"
              className="inline-flex min-h-11 min-w-11 items-center justify-center gap-1.5 rounded-xl border border-border-default bg-surface-1 px-3 text-sm font-semibold text-foreground transition hover:bg-surface-2"
              href={publicPath}
              rel="noopener noreferrer"
              target="_blank"
            >
              <ExternalLinkIcon className="h-4 w-4" />
              <span>Open</span>
            </a>
            {role === "owner" ? (
              <button
                className="inline-flex min-h-11 min-w-11 items-center justify-center rounded-xl border border-border-default bg-surface-1 px-3 text-sm font-semibold text-foreground transition hover:bg-surface-2"
                onClick={() => setChangingSlug(true)}
                type="button"
              >
                Change address
              </button>
            ) : null}
          </div>
        </div>
      </div>
      {/* Mounted only while open so the dialog's hooks never run for non-owners. */}
      {changingSlug ? (
        <OrganizationSlugDialog onClose={() => setChangingSlug(false)} open />
      ) : null}
      {changingCountry ? (
        <OrganizationCountryDialog onClose={() => setChangingCountry(false)} open />
      ) : null}

      <dl className="grid grid-cols-2 gap-4 border-t border-border-default pt-4 sm:grid-cols-3 lg:grid-cols-5">
        <div>
          <dt className="text-xs text-foreground-muted">Your role</dt>
          <dd className="mt-1">
            <StatusPill status={role} />
          </dd>
        </div>
        <div>
          <dt className="text-xs text-foreground-muted">Members</dt>
          <dd className="mt-1 text-sm font-semibold text-foreground">
            {memberCount === null ? "—" : memberCount}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-foreground-muted">Created</dt>
          <dd className="mt-1 text-sm font-semibold text-foreground">
            {formatDate(org.created_at)}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-foreground-muted">Verified</dt>
          <dd className="mt-1 text-sm font-semibold text-foreground">
            {isVerified ? (kybVerifiedAt ? formatDate(kybVerifiedAt) : "Yes") : "Not yet"}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-foreground-muted">Country</dt>
          <dd className="mt-1 text-sm font-semibold text-foreground">{countryName(org.country)}</dd>
          {role === "owner" ? (
            countryLocked ? (
              <p className="mt-1 text-xs text-foreground-muted">Locked after verification</p>
            ) : (
              <button
                className="mt-1 inline-flex min-h-11 items-center text-sm font-semibold text-accent underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
                onClick={() => setChangingCountry(true)}
                type="button"
              >
                Change country
              </button>
            )
          ) : null}
        </div>
      </dl>
    </section>
  );
}
