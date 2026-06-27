/**
 * Authenticated account identity and verification route.
 *
 * Shows the private identity, email-verification, and KYC summary. Editing the
 * public-facing profile lives on the owner's own profile page (/profile/me) or
 * edit page (/profile/edit).
 */
import Link from "next/link";

import { ProfileSettingsPanel } from "@/components/modules/settings/profile-settings-panel";

/**
 * Render the authenticated account identity settings page.
 */
export default function IdentitySettingsPage() {
  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <header className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm md:p-8">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
              Account
            </p>
            <h1 className="mt-2 font-heading text-3xl font-bold text-foreground md:text-4xl">
              Identity and verification
            </h1>
            <p className="mt-3 max-w-2xl text-sm leading-6 text-foreground-muted">
              Review the private identity, email verification, and KYC details on
              your account. To edit what others see, update your public profile.
            </p>
          </div>
          <Link
            className="inline-flex min-h-12 shrink-0 items-center justify-center rounded-xl bg-foreground px-5 text-sm font-semibold text-background transition-all hover:bg-foreground/90 active:scale-[0.98]"
            href="/profile/me"
          >
            View public profile
          </Link>
        </div>
      </header>
      <section className="rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm md:p-6">
        <ProfileSettingsPanel />
      </section>
    </div>
  );
}

