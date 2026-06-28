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
import { CheckCircledIcon, GlobeIcon, StarFilledIcon } from "@radix-ui/react-icons";
import type { ReactNode } from "react";

import {
  AttestationBadge,
  FrameworkCard,
} from "@/components/modules/explore/framework-card";
import {
  KycSeal,
  RoleBadge,
} from "@/components/modules/profiles/profile-badges";
import { SOCIAL_PLATFORM_MAP } from "@/components/modules/profiles/social-platforms";
import { ReputationBadge } from "@/components/modules/reputation/reputation-badge";
import { RatingStars } from "@/components/modules/reputation/rating-stars";
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
  const socialLinks = profile.social_links ?? [];
  const experience = profile.experience ?? [];
  const education = profile.education ?? [];
  const featured = profile.featured ?? [];
  const stats = profile.stats ?? {};
  const frameworksPublished = stats.frameworks_published ?? 0;
  const reviewsReceived = stats.reviews_received ?? 0;
  const attestationsPerformed = stats.attestations_performed ?? 0;
  const averageRating = stats.average_rating ?? null;
  const hasStats =
    frameworksPublished > 0 || reviewsReceived > 0 || attestationsPerformed > 0;
  const websiteHref = safeHref(profile.website);

  return (
    <div className="mx-auto max-w-[1280px] space-y-8">
      {/* Identity header — verified accounts get the accent avatar ring. */}
      <section className="rounded-2xl border border-border-default bg-surface-1 shadow-bento overflow-hidden">
        {profile.banner_url ? (
          <div
            aria-hidden="true"
            className="h-36 w-full bg-cover bg-center border-b border-border-default bg-surface-2 sm:h-48 md:h-56"
            style={{ backgroundImage: `url(${profile.banner_url})` }}
          />
        ) : (
          <div className="h-20 w-full bg-surface-2 border-b border-border-default sm:h-24" />
        )}

        <div className="p-6 md:p-8">
          <div className="flex flex-col items-start gap-6 md:flex-row">
            <div className="shrink-0 relative z-10 -mt-16 md:-mt-20">
              <div
                className={[
                  "flex h-24 w-24 items-center justify-center overflow-hidden rounded-2xl bg-surface-3 md:h-28 md:w-28 shadow-sm",
                  profile.kyc_verified ? "ring-2 ring-accent ring-offset-4 ring-offset-surface-1" : ""
                ].join(" ")}
              >
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

            {socialLinks.length > 0 ? (
              <ul className="mt-5 flex flex-wrap items-center gap-2">
                {socialLinks.map((social) => {
                  const meta = SOCIAL_PLATFORM_MAP[social.platform];
                  const href = safeHref(social.url);
                  if (!meta || !href) {
                    return null;
                  }
                  const Icon = meta.Icon;
                  return (
                    <li key={social.platform}>
                      <a
                        aria-label={meta.label}
                        className="flex h-11 w-11 items-center justify-center rounded-xl border border-border-default bg-surface-1 text-foreground-muted transition-colors hover:border-accent/30 hover:bg-surface-2 hover:text-accent"
                        href={href}
                        rel="noreferrer noopener"
                        target="_blank"
                        title={meta.label}
                      >
                        <Icon className="h-5 w-5" />
                      </a>
                    </li>
                  );
                })}
              </ul>
            ) : null}
          </div>
        </div>
      </div>
    </section>

      {hasStats ? (
        <section className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          {[
            { label: "Frameworks", value: String(frameworksPublished) },
            {
              label: "Avg rating",
              value: averageRating === null ? "—" : (
                <div className="flex items-center gap-1.5">
                  <RatingStars rating={averageRating} starClassName="h-4 w-4" />
                  <span className="text-sm font-semibold text-foreground-muted ml-0.5 mt-0.5">
                    ({reviewsReceived})
                  </span>
                </div>
              ),
            },
            { label: "Attestations", value: String(attestationsPerformed) },
          ].map((tile) => (
            <div
              className="rounded-2xl border border-border-default bg-surface-1 p-4 shadow-sm"
              key={tile.label}
            >
              <div className="font-heading text-2xl font-extrabold tracking-tight text-foreground flex items-center h-8">
                {tile.value}
              </div>
              <p className="mt-1 text-[11px] font-semibold uppercase tracking-[0.05em] text-foreground-subtle">
                {tile.label}
              </p>
            </div>
          ))}
        </section>
      ) : null}

      {featured.length > 0 ? (
        <section>
          <h2 className="mb-4 border-b border-border-default pb-4 font-heading text-xl font-bold text-foreground">
            Featured
          </h2>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {featured.map((item, index) => {
              if (item.framework) {
                return (
                  <FrameworkCard
                    framework={item.framework}
                    key={`fw-${item.framework.id}-${index}`}
                  />
                );
              }
              const href = safeHref(item.url);
              const card = (
                <>
                  <h3 className="font-heading text-lg font-bold text-foreground">
                    {item.title}
                  </h3>
                  {item.description ? (
                    <p className="mt-2 text-sm leading-relaxed text-foreground-muted">
                      {item.description}
                    </p>
                  ) : null}
                  {href ? (
                    <span className="mt-3 inline-flex items-center gap-1.5 text-sm font-semibold text-accent">
                      View
                      <GlobeIcon className="h-4 w-4" aria-hidden="true" />
                    </span>
                  ) : null}
                </>
              );
              return href ? (
                <a
                  className="block rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm transition-colors hover:border-accent/30 hover:bg-surface-2"
                  href={href}
                  key={`${item.title}-${index}`}
                  rel="noreferrer noopener"
                  target="_blank"
                >
                  {card}
                </a>
              ) : (
                <div
                  className="rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm"
                  key={`${item.title}-${index}`}
                >
                  {card}
                </div>
              );
            })}
          </div>
        </section>
      ) : null}

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

      {experience.length > 0 ? (
        <section>
          <div className="mb-4 flex items-end justify-between border-b border-border-default pb-4">
            <h2 className="font-heading text-xl font-bold text-foreground">
              Experience
            </h2>
            <span className="text-[10px] font-semibold uppercase tracking-[0.05em] text-foreground-subtle">
              Self-reported
            </span>
          </div>
          <ul className="space-y-4">
            {experience.map((item, index) => (
              <li
                className="rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm"
                key={`${item.title}-${item.company}-${index}`}
              >
                <div className="flex flex-wrap items-baseline justify-between gap-x-3">
                  <h3 className="font-heading text-lg font-bold text-foreground">
                    {item.title}
                  </h3>
                  <span className="text-xs font-semibold uppercase tracking-[0.05em] text-foreground-subtle">
                    {[item.start, item.current ? "Present" : item.end]
                      .filter(Boolean)
                      .join(" – ")}
                  </span>
                </div>
                <p className="mt-0.5 text-sm font-semibold text-foreground-muted">
                  {item.company}
                </p>
                {item.description ? (
                  <p className="mt-2 text-sm leading-relaxed text-foreground-muted">
                    {item.description}
                  </p>
                ) : null}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {education.length > 0 ? (
        <section>
          <div className="mb-4 flex items-end justify-between border-b border-border-default pb-4">
            <h2 className="font-heading text-xl font-bold text-foreground">
              Education
            </h2>
            <span className="text-[10px] font-semibold uppercase tracking-[0.05em] text-foreground-subtle">
              Self-reported
            </span>
          </div>
          <ul className="space-y-4">
            {education.map((item, index) => (
              <li
                className="rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm"
                key={`${item.school}-${index}`}
              >
                <div className="flex flex-wrap items-baseline justify-between gap-x-3">
                  <h3 className="font-heading text-lg font-bold text-foreground">
                    {item.school}
                  </h3>
                  <span className="text-xs font-semibold uppercase tracking-[0.05em] text-foreground-subtle">
                    {[item.start_year, item.end_year].filter(Boolean).join(" – ")}
                  </span>
                </div>
                {item.degree || item.field ? (
                  <p className="mt-0.5 text-sm font-semibold text-foreground-muted">
                    {[item.degree, item.field].filter(Boolean).join(", ")}
                  </p>
                ) : null}
              </li>
            ))}
          </ul>
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
