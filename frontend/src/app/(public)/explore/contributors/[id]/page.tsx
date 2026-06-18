/**
 * Public Contributor profile route.
 *
 * Server-rendered Explore page showing safe public identity fields, public
 * Attestation context, and the Contributor's newest published Frameworks.
 */
import {
  ArchiveIcon,
  ArrowLeftIcon,
  CheckCircledIcon,
  GlobeIcon,
} from "@radix-ui/react-icons";
import Link from "next/link";
import { notFound } from "next/navigation";

import {
  AttestationBadge,
  FrameworkCard,
} from "@/components/modules/explore/framework-card";
import { ReputationBadge } from "@/components/modules/reputation/reputation-badge";
import { getExploreContributorProfile } from "@/lib/generated/sdk.gen";
import type { ExploreContributorProfile } from "@/lib/generated/types.gen";
import { configureServerMarketplaceClient } from "@/lib/marketplace/api";
import { safeHref } from "@/lib/url/safe-href";

type ContributorProfilePageProps = {
  params: Promise<{ id: string }>;
};

/**
 * Render a public Contributor profile page.
 *
 * @param props - Next.js route params.
 */
export default async function ContributorProfilePage({
  params,
}: ContributorProfilePageProps) {
  const { id } = await params;

  configureServerMarketplaceClient();
  const result = await getExploreContributorProfile({
    path: { contributor_id: id },
  });

  if (!result.response.ok || !result.data) {
    notFound();
  }

  const profile: ExploreContributorProfile = result.data;
  const verifiedCredentials = profile.verified_credentials ?? [];
  const reportLabel =
    profile.attestation_count === 1
      ? "1 public report"
      : `${profile.attestation_count} public reports`;

  return (
    <main className="px-4 py-8 text-foreground md:px-8">
      <div className="mx-auto max-w-[1280px]">
        <Link
          className="inline-flex items-center gap-1.5 text-sm font-semibold text-accent transition-colors hover:text-accent/80"
          href="/explore"
        >
          <ArrowLeftIcon className="h-4 w-4" />
          Back to Explore
        </Link>

        <section className="mt-6 rounded-2xl border border-border-default bg-surface-1 p-6 md:p-8 shadow-bento transition-all duration-300 hover:border-accent/20">
          <div className="flex flex-col md:flex-row gap-6 items-start w-full">
            {/* Avatar block with premium borders */}
            <div className="relative flex h-24 w-24 md:h-28 md:w-28 items-center justify-center overflow-hidden rounded-2xl border border-border-default bg-surface-2 shadow-sm transition-all duration-300 group hover:border-accent/40 hover:shadow-bento shrink-0">
              {profile.avatar_url ? (
                <div
                  aria-hidden="true"
                  className="h-full w-full bg-cover bg-center transition-transform duration-500 group-hover:scale-105"
                  style={{ backgroundImage: `url(${profile.avatar_url})` }}
                />
              ) : (
                <span className="font-heading text-4xl font-extrabold text-accent">
                  {profile.display_name.slice(0, 1).toUpperCase()}
                </span>
              )}
            </div>

            <div className="min-w-0 flex-1 w-full">
              {/* Header and website button row */}
              <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-4 border-b border-border-default/50 pb-5">
                <div>
                  <div className="flex flex-wrap items-center gap-2 mb-2">
                    {profile.reputation ? (
                      <ReputationBadge
                        score={profile.reputation.score ?? null}
                        isProvisional={profile.reputation.is_provisional ?? true}
                        factors={profile.reputation.factors ?? []}
                      />
                    ) : null}
                    {profile.attestation_badge ? (
                      <AttestationBadge badge={profile.attestation_badge} />
                    ) : null}
                    {profile.is_deactivated ? (
                      <span className="rounded-md border border-border-default bg-surface-2 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.05em] text-foreground-muted">
                        Read-only profile
                      </span>
                    ) : null}
                  </div>
                  <h1 className="font-heading text-3xl font-extrabold tracking-tight text-foreground md:text-4xl">
                    {profile.display_name}
                  </h1>
                </div>

                {safeHref(profile.website) ? (
                  <a
                    className="inline-flex min-h-12 items-center justify-center rounded-xl bg-foreground px-5 text-sm font-semibold text-background transition-all hover:bg-foreground/90 active:scale-[0.98] shrink-0 text-center"
                    href={safeHref(profile.website)}
                    rel="noreferrer noopener"
                    target="_blank"
                  >
                    Visit website
                  </a>
                ) : null}
              </div>

              {profile.bio ? (
                <p className="mt-4 max-w-4xl text-base leading-relaxed text-foreground-muted">
                  {profile.bio}
                </p>
              ) : null}

              {/* Bento Stats Grid */}
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mt-6">
                {/* Frameworks Stat Box */}
                <div className="rounded-xl border border-border-default/50 bg-surface-2 p-4 flex items-center gap-3.5 transition-all duration-300 hover:border-accent/20 hover:bg-surface-3/30 hover:shadow-sm">
                  <div className="p-2.5 bg-accent/5 rounded-xl text-accent shrink-0 flex items-center justify-center border border-accent/10">
                    <ArchiveIcon className="h-5 w-5" aria-hidden="true" />
                  </div>
                  <div>
                    <span className="text-[10px] font-bold uppercase tracking-[0.05em] text-foreground-muted block">Frameworks</span>
                    <span className="text-sm font-semibold text-foreground mt-0.5 block">{profile.published_framework_count} published</span>
                  </div>
                </div>

                {/* Attestations Stat Box */}
                <div className="rounded-xl border border-border-default/50 bg-surface-2 p-4 flex items-center gap-3.5 transition-all duration-300 hover:border-accent/20 hover:bg-surface-3/30 hover:shadow-sm">
                  <div className="p-2.5 bg-accent/5 rounded-xl text-accent shrink-0 flex items-center justify-center border border-accent/10">
                    <CheckCircledIcon className="h-5 w-5" aria-hidden="true" />
                  </div>
                  <div>
                    <span className="text-[10px] font-bold uppercase tracking-[0.05em] text-foreground-muted block">Attestations</span>
                    <span className="text-sm font-semibold text-foreground mt-0.5 block">{reportLabel}</span>
                  </div>
                </div>

                {/* Location Stat Box */}
                <div className="rounded-xl border border-border-default/50 bg-surface-2 p-4 flex items-center gap-3.5 transition-all duration-300 hover:border-accent/20 hover:bg-surface-3/30 hover:shadow-sm">
                  <div className="p-2.5 bg-accent/5 rounded-xl text-accent shrink-0 flex items-center justify-center border border-accent/10">
                    <GlobeIcon className="h-5 w-5" aria-hidden="true" />
                  </div>
                  <div>
                    <span className="text-[10px] font-bold uppercase tracking-[0.05em] text-foreground-muted block">Location</span>
                    <span className="text-sm font-semibold text-foreground mt-0.5 block">{profile.location ?? "Not listed"}</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </section>

        <section className="mt-10">
          <div className="mb-4 flex flex-col gap-2 border-b border-border-default pb-4 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <h2 className="font-heading text-xl font-bold text-foreground">
                Published Frameworks
              </h2>
              <p className="mt-1 text-sm text-foreground-muted">
                Showing the newest published Frameworks by this Contributor.
              </p>
            </div>
            <p className="text-sm font-semibold text-foreground-muted">
              {profile.published_frameworks.length} shown
            </p>
          </div>

          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {profile.published_frameworks.map((framework) => (
              <FrameworkCard framework={framework} key={framework.id} />
            ))}
          </div>
        </section>

        {verifiedCredentials.length > 0 ? (
          <section className="mt-10">
            <div className="mb-4 border-b border-border-default pb-4">
              <h2 className="font-heading text-xl font-bold text-foreground">
                Verified credentials
              </h2>
              <p className="mt-1 text-sm text-foreground-muted">
                Professional credentials independently verified by Auracles.
              </p>
            </div>

            <ul className="grid gap-4 sm:grid-cols-2">
              {verifiedCredentials.map((credential, index) => (
                <li
                  className="rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm"
                  key={`${credential.title}-${credential.issuer}-${index}`}
                >
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <h3 className="font-heading text-lg font-bold text-foreground">
                      {credential.title}
                    </h3>
                    <span className="inline-flex h-7 items-center gap-1.5 rounded-badge border border-success/30 bg-success/10 px-2 text-xs font-medium uppercase tracking-[0.05em] text-success">
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
    </main>
  );
}
