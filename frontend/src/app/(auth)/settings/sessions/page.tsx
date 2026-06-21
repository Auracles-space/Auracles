/**
 * Authenticated session settings route.
 *
 * Middleware requires a signed session hint before this page renders; API
 * calls still use the generated client with bearer access tokens.
 */
import { SessionList } from "@/components/modules/settings/session-list";

export default function SessionsSettingsPage() {
  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <header className="mb-6">
        <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
          Session security
        </p>
        <h1 className="mt-2 font-heading text-3xl font-bold text-foreground">
          Manage active browser sessions
        </h1>
        <p className="mt-3 text-sm leading-6 text-foreground-muted">
          Review where your account is active and revoke refresh-token
          sessions that should no longer have access.
        </p>
      </header>
      <section className="rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm">
        <SessionList autoload />
      </section>
    </div>
  );
}
