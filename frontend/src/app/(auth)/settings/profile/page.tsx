/**
 * Authenticated private profile route.
 *
 * Surfaces the user's own identity, email-verification state, and KYC summary
 * using existing auth/settings APIs. This route is private and distinct from
 * the public contributor profile surface.
 */
import { ProfileSettingsPanel } from "@/components/modules/settings/profile-settings-panel";

/**
 * Render the authenticated private profile page.
 */
export default function ProfileSettingsPage() {
  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <header className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm md:p-8">
        <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
          Private profile
        </p>
        <h1 className="mt-2 font-heading text-3xl font-bold text-foreground md:text-4xl">
          Identity and verification
        </h1>
        <p className="mt-3 max-w-2xl text-sm leading-6 text-foreground-muted">
          Review the private identity details attached to your account, along
          with email verification and KYC progress.
        </p>
      </header>
      <section className="rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm md:p-6">
        <ProfileSettingsPanel />
      </section>
    </div>
  );
}
