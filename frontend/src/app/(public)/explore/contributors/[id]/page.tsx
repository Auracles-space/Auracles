/**
 * Public Contributor profile route.
 *
 * Server-rendered Explore page showing safe public identity fields, public
 * Attestation context, and the Contributor's newest published Frameworks.
 */
import Link from "next/link";
import { notFound } from "next/navigation";

import {
  AttestationBadge,
  FrameworkCard,
} from "@/components/modules/explore/framework-card";
import { getExploreContributorProfile } from "@/lib/generated/sdk.gen";
import type { ExploreContributorProfile } from "@/lib/generated/types.gen";
import { configureServerMarketplaceClient } from "@/lib/marketplace/api";

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
  const reportLabel =
    profile.attestation_count === 1
      ? "1 public report"
      : `${profile.attestation_count} public reports`;

  return (
    <main className="min-h-screen bg-background px-4 py-8 text-foreground md:px-8">
      <div className="mx-auto max-w-[1280px]">
        <Link className="text-sm font-semibold text-accent" href="/explore">
          Back to Explore
        </Link>

        <section className="mt-6 rounded-2xl border border-border-default bg-surface-1 p-5 md:p-8 shadow-sm">
          <div className="grid gap-6 md:grid-cols-[96px_1fr]">
            <div className="flex h-24 w-24 items-center justify-center overflow-hidden rounded-2xl border border-border-default bg-surface-2 shadow-sm">
              {profile.avatar_url ? (
                <div
                  aria-hidden="true"
                  className="h-full w-full bg-cover bg-center"
                  style={{ backgroundImage: `url(${profile.avatar_url})` }}
                />
              ) : (
                <span className="font-heading text-3xl font-bold text-foreground">
                  {profile.display_name.slice(0, 1).toUpperCase()}
                </span>
              )}
            </div>

            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                {profile.attestation_badge ? (
                  <AttestationBadge badge={profile.attestation_badge} />
                ) : null}
                {profile.is_deactivated ? (
                  <span className="rounded-[4px] border border-border-default bg-surface-2 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.05em] text-foreground-muted">
                    Read-only profile
                  </span>
                ) : null}
              </div>

              <h1 className="mt-3 font-heading text-3xl font-bold text-foreground md:text-5xl">
                {profile.display_name}
              </h1>

              {profile.bio ? (
                <p className="mt-4 max-w-3xl text-base leading-7 text-foreground-muted">
                  {profile.bio}
                </p>
              ) : null}

              <dl className="mt-5 grid gap-3 text-sm text-foreground-muted sm:grid-cols-3">
                <div>
                  <dt className="font-semibold text-foreground">Frameworks</dt>
                  <dd>{profile.published_framework_count} published</dd>
                </div>
                <div>
                  <dt className="font-semibold text-foreground">Attestations</dt>
                  <dd>{reportLabel}</dd>
                </div>
                <div>
                  <dt className="font-semibold text-foreground">Location</dt>
                  <dd>{profile.location ?? "Not listed"}</dd>
                </div>
              </dl>

              {profile.website ? (
                <a
                  className="mt-5 inline-flex min-h-11 items-center text-sm font-semibold text-accent transition hover:text-accent/80"
                  href={profile.website}
                  rel="noreferrer"
                  target="_blank"
                >
                  Visit website
                </a>
              ) : null}
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
      </div>
    </main>
  );
}
