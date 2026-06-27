/**
 * Profile presentation.
 *
 * The single visual representation of an Auracles Profile, shared by the public
 * SSR page and the owner's own page. Verification is the visual reward: a
 * KYC-verified account gets the brand accent avatar ring and identity seal,
 * while self-reported headline and bio stay quiet.
 *
 * Stateless and server-safe (no hooks) so it renders in both server and client
 * trees. Owner-only controls are injected via the headerAction slot.
 *
 * Maps to: FR-SET-001/002.
 */
import { CheckCircledIcon, GlobeIcon } from "@radix-ui/react-icons";
import type { ReactNode } from "react";

import {
  AttestationBadge,
  FrameworkCard,
} from "@/components/modules/explore/framework-card";
import {
  KycSeal,
  RoleBadge,
} from "@/components/modules/profiles/profile-badges";
import { ReputationBadge } from "@/components/modules/reputation/reputation-badge";
import type {
  ExploreAttestationBadge,
  ExploreFrameworkCard,
  PublicProfileResponse,
  ReputationSummary,
} from "@/lib/generated/types.gen";
import { safeHref } from "@/lib/url/safe-href";

type ProfileViewProps = {
  profile: PublicProfileResponse;
  headerAction?: ReactNode;
  /** Contributor reputation, shown as a header badge when present. */
  reputation?: ReputationSummary | null;
  /** Contributor attestation badge, shown beside reputation when present. */
  attestationBadge?: ExploreAttestationBadge | null;
  /** A Contributor's published Frameworks, shown in their own section. */
  frameworks?: ExploreFrameworkCard[];
};

/**
 * Derive up-to-two-letter initials for the avatar fallback.
 *
 * @param name - The profile display name.
 */
function initials(name: string): string {
  return (
    name
      .trim()
      .split(/\s+/)
      .map((word) => word[0])
      .join("")
      .slice(0, 2)
      .toUpperCase() || "A"
  );
}

/**
 * Render the full profile presentation.
 *
 * @param props - The profile payload and an optional owner-action slot shown in
 *   the header (e.g. an "Edit profile" button on the owner's own page).
 */
export function ProfileView({
  profile,
  headerAction,
  reputation,
  attestationBadge,
  frameworks = [],
}: ProfileViewProps) {
  const credentials = profile.verified_credentials ?? [];
  const specializations = profile.specializations ?? [];
  const links = profile.links ?? [];
  const websiteHref = safeHref(profile.website);

  return (
    <div className="mx-auto max-w-[1280px] space-y-8">
      {/* Identity header — verified accounts get the accent avatar ring. */}
      <section className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-bento md:p-8">
        <div className="flex flex-col items-start gap-6 md:flex-row">
          <div className="shrink-0 rounded-2xl border border-border-default p-1 bg-surface-2">
            <div className="flex h-24 w-24 items-center justify-center overflow-hidden rounded-[14px] bg-surface-3 md:h-28 md:w-28">
              {profile.avatar_url ? (
                <div
                  aria-hidden="true"
                  className="h-full w-full bg-cover bg-center"
                  style={{ backgroundImage: `url(${profile.avatar_url})` }}
                />
              ) : (
                <span className="font-heading text-3xl font-extrabold tracking-tighter text-accent">
                  {initials(profile.display_name)}
                </span>
              )}
            </div>
          </div>

          <div className="min-w-0 flex-1">
            <div className="flex flex-col gap-4 border-b border-border-default pb-5 sm:flex-row sm:items-start sm:justify-between">
              <div className="space-y-2">
                <h1 className="font-heading text-3xl font-extrabold tracking-tight text-foreground md:text-4xl">
                  {profile.display_name}
                </h1>
                {profile.headline ? (
                  <p className="max-w-2xl text-sm leading-6 text-foreground-muted">
                    {profile.headline}
                  </p>
                ) : null}
                <div className="flex flex-wrap items-center gap-1.5 pt-1">
                  <KycSeal verified={profile.kyc_verified ?? false} />
                  {reputation ? (
                    <ReputationBadge
                      factors={reputation.factors ?? []}
                      isProvisional={reputation.is_provisional ?? true}
                      score={reputation.score ?? null}
                    />
                  ) : null}
                  {attestationBadge ? (
                    <AttestationBadge badge={attestationBadge} />
                  ) : null}
                  {(profile.roles ?? []).map((role) => (
                    <RoleBadge key={role} role={role} />
                  ))}
                  {profile.is_deactivated ? (
                    <span className="inline-flex h-7 items-center rounded-badge border border-border-default bg-surface-2 px-2.5 text-xs font-bold uppercase tracking-[0.05em] text-foreground-muted">
                      Read-only
                    </span>
                  ) : null}
                </div>
              </div>

              <div className="flex shrink-0 flex-wrap items-center gap-2">
                {headerAction}
                {websiteHref ? (
                  <a
                    className="inline-flex h-9 items-center justify-center rounded-xl bg-foreground px-4 text-sm font-semibold text-background transition-all hover:bg-foreground/90 active:scale-[0.98]"
                    href={websiteHref}
                    rel="noreferrer noopener"
                    target="_blank"
                  >
                    Visit website
                  </a>
                ) : null}
              </div>
            </div>

            {profile.location ? (
              <p className="mt-4 inline-flex items-center gap-1.5 text-sm text-foreground-muted">
                <svg className="h-4 w-4 shrink-0 text-foreground-muted" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z" />
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 11a3 3 0 11-6 0 3 3 0 016 0z" />
                </svg>
                {profile.location}
              </p>
            ) : null}

            {profile.bio ? (
              <p className="mt-4 max-w-3xl text-base leading-relaxed text-foreground-muted">
                {profile.bio}
              </p>
            ) : null}

            {specializations.length > 0 ? (
              <ul className="mt-5 flex flex-wrap gap-2">
                {specializations.map((item) => (
                  <li
                    className="rounded-full border border-border-strong bg-surface-2 px-3 py-1.5 text-xs font-semibold text-foreground"
                    key={item}
                  >
                    {item}
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
        </div>
      </section>

      {links.length > 0 ? (
        <section>
          <h2 className="mb-4 border-b border-border-default pb-4 font-heading text-xl font-bold text-foreground">
            Links
          </h2>
          <ul className="grid gap-3 sm:grid-cols-2">
            {links.map((link, index) => {
              const href = safeHref(link.url);
              return (
                <li key={`${link.label}-${index}`}>
                  {href ? (
                    <a
                      className="flex min-h-12 items-center gap-2 rounded-xl border border-border-default bg-surface-1 px-4 text-sm font-semibold text-accent transition-colors hover:border-accent/30 hover:bg-surface-2"
                      href={href}
                      rel="noreferrer noopener"
                      target="_blank"
                    >
                      <GlobeIcon className="h-4 w-4 shrink-0" aria-hidden="true" />
                      {link.label}
                    </a>
                  ) : null}
                </li>
              );
            })}
          </ul>
        </section>
      ) : null}

      {frameworks.length > 0 ? (
        <section>
          <div className="mb-4 border-b border-border-default pb-4">
            <h2 className="font-heading text-xl font-bold text-foreground">
              Published Frameworks
            </h2>
            <p className="mt-1 text-sm text-foreground-muted">
              The newest published Frameworks by this Contributor.
            </p>
          </div>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {frameworks.map((framework) => (
              <FrameworkCard framework={framework} key={framework.id} />
            ))}
          </div>
        </section>
      ) : null}

      {credentials.length > 0 ? (
        <section>
          <div className="mb-4 border-b border-border-default pb-4">
            <h2 className="font-heading text-xl font-bold text-foreground">
              Verified credentials
            </h2>
            <p className="mt-1 text-sm text-foreground-muted">
              Professional credentials independently verified by Auracles.
            </p>
          </div>
          <ul className="grid gap-4 sm:grid-cols-2">
            {credentials.map((credential, index) => (
              <li
                className="rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm"
                key={`${credential.title}-${credential.issuer}-${index}`}
              >
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <h3 className="font-heading text-lg font-bold text-foreground">
                    {credential.title}
                  </h3>
                  <span className="inline-flex h-7 items-center gap-1.5 rounded-badge border border-success/30 bg-success/10 px-2 text-xs font-medium uppercase tracking-[0.05em] text-success">
                    <CheckCircledIcon className="h-3.5 w-3.5" aria-hidden="true" />
                    Verified
                  </span>
                </div>
                <p className="mt-1 text-sm text-foreground-muted">
                  {credential.issuer}
                  {credential.credential_type
                    ? ` · ${credential.credential_type}`
                    : ""}
                </p>
                <p className="mt-2 text-xs font-semibold uppercase tracking-[0.05em] text-foreground-muted">
                  Issued {credential.issued_date}
                  {credential.expires_date
                    ? ` · ${credential.expired ? "expired" : "expires"} ${credential.expires_date}`
                    : ""}
                </p>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
