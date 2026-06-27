/**
 * Public Auracles Profile route.
 *
 * Server-rendered identity page for any platform user (Contributor, Operator,
 * Attestor). Renders the shared ProfileView from curated public fields.
 * Suspended accounts return a limited profile (safe identity only), never 404.
 *
 * Maps to: FR-SET-001/002.
 */
import { notFound } from "next/navigation";

import { BackButton } from "@/components/ui/back-button";
import { loadContributorExtras } from "@/components/modules/profiles/contributor-extras";
import { ProfileView } from "@/components/modules/profiles/profile-view";
import { getPublicProfileV1ProfilesUserIdGet } from "@/lib/generated/sdk.gen";
import { configureServerMarketplaceClient } from "@/lib/marketplace/api";

type ProfilePageProps = {
  params: Promise<{ id: string }>;
};

/**
 * Render a public Auracles Profile page.
 *
 * @param props - Next.js route params carrying the profile owner's id.
 */
export default async function ProfilePage({ params }: ProfilePageProps) {
  const { id } = await params;

  configureServerMarketplaceClient();
  const result = await getPublicProfileV1ProfilesUserIdGet({
    path: { user_id: id },
  });

  if (!result.response.ok || !result.data) {
    notFound();
  }

  const extras = await loadContributorExtras(id, result.data.roles ?? []);

  return (
    <main className="px-4 py-8 text-foreground md:px-8">
      <div className="mx-auto max-w-[1280px] space-y-6">
        <BackButton fallbackHref="/explore">
          Back to Explore
        </BackButton>
        <ProfileView
          attestationBadge={extras.attestationBadge}
          frameworks={extras.frameworks}
          profile={result.data}
          reputation={extras.reputation}
        />
      </div>
    </main>
  );
}
