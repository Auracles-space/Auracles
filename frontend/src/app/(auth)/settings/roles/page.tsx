/**
 * Authenticated account roles route.
 *
 * Home for adding a marketplace role to an existing account. Before this
 * existed, roles could only be chosen during first-run onboarding, so a
 * Contributor who later wanted to post a Project had no route to one.
 *
 * Maps to: FR-AUTH-013, FR-SET-002.
 */
import { AccountRolesPanel } from "@/components/modules/settings/account-roles-panel";

/**
 * Render the authenticated account roles settings page.
 */
export default function RolesSettingsPage() {
  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <header className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm md:p-8">
        <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
          Account
        </p>
        <h1 className="mt-2 font-heading text-3xl font-bold text-foreground md:text-4xl">
          Roles and access
        </h1>
        <p className="mt-3 max-w-2xl text-sm leading-6 text-foreground-muted">
          Choose how you use Auracles. Adding a role opens new marketplace
          actions without changing anything you already have.
        </p>
      </header>
      <section className="rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm md:p-6">
        <AccountRolesPanel />
      </section>
    </div>
  );
}
