"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { BackButton } from "@/components/ui/back-button";
import {
  type ContributorExtras,
  loadContributorExtras,
} from "@/components/modules/profiles/contributor-extras";
import { ProfileView } from "@/components/modules/profiles/profile-view";
import ProfileLoading from "../loading";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import { getMyProfileV1ProfilesMeGet } from "@/lib/generated/sdk.gen";
import type { PublicProfileResponse } from "@/lib/generated/types.gen";

/**
 * The owner's own profile page.
 *
 * Renders the owner's profile exactly as the public sees it (ProfileView).
 * Provides an "Edit profile" action that routes to the dedicated editor at `/profile/edit`.
 *
 * Static route resolves ahead of the dynamic /profile/[id] in the same group.
 *
 * Maps to: FR-SET-001/002.
 */
export default function MyProfilePage() {
  const [profile, setProfile] = useState<PublicProfileResponse | null>(null);
  const [extras, setExtras] = useState<ContributorExtras | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;
    async function load(): Promise<void> {
      configureBrowserClient();
      const result = await getMyProfileV1ProfilesMeGet({
        headers: getAccessTokenHeaders(),
      });
      if (!mounted) {
        return;
      }
      if (result.data) {
        setProfile(result.data);
        const loaded = await loadContributorExtras(
          result.data.id,
          result.data.roles ?? [],
        );
        if (mounted) {
          setExtras(loaded);
        }
      } else {
        setError(describeGeneratedError(result.error));
      }
      setLoading(false);
    }
    void load();
    return () => {
      mounted = false;
    };
  }, []);

  return (
    <main className="px-4 py-8 text-foreground md:px-8">
      {loading ? <ProfileLoading /> : null}

      {!loading && !profile ? (
        <div className="mx-auto max-w-[1280px] space-y-3">
          <p className="text-sm text-error">
            {error ?? "Your profile could not be loaded."}
          </p>
          <Link
            className="text-sm font-semibold text-accent hover:text-accent/80"
            href="/login?next=/profile/me"
          >
            Sign in to view your profile
          </Link>
        </div>
      ) : null}

      {profile ? (
        <div className="mx-auto max-w-[1280px] space-y-6">
          <BackButton fallbackHref="/explore" className="text-sm font-semibold text-accent">
            &larr; Back
          </BackButton>
          <ProfileView
            attestationBadge={extras?.attestationBadge ?? null}
            frameworks={extras?.frameworks ?? []}
            headerAction={
              <Link
                className="inline-flex h-9 items-center justify-center rounded-xl border border-border-default bg-surface-1 px-4 text-sm font-medium text-foreground shadow-[0_1px_2px_rgba(0,0,0,0.02)] transition hover:bg-surface-2"
                href="/profile/edit"
              >
                Edit profile
              </Link>
            }
            profile={profile}
            reputation={extras?.reputation ?? null}
          />
        </div>
      ) : null}
    </main>
  );
}
