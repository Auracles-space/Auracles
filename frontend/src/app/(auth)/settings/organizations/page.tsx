/**
 * Authenticated organizations settings route.
 *
 * Hosts organization memberships and pending invitation resolution for the
 * authenticated user.
 */
import { OrganizationsPanel } from "@/components/modules/settings/organizations-panel";

/**
 * Render authenticated organization settings.
 */
export default function OrganizationsSettingsPage() {
  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <header className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm md:p-8">
        <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
          Organization settings
        </p>
        <h1 className="mt-2 font-heading text-3xl font-bold text-foreground md:text-4xl">
          Organizations
        </h1>
        <p className="mt-3 max-w-2xl text-sm leading-6 text-foreground-muted">
          Review your organization memberships and resolve invitations sent to
          your account email.
        </p>
      </header>
      <OrganizationsPanel />
    </div>
  );
}
