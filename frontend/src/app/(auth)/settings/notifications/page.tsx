/**
 * Authenticated notification settings route.
 *
 * Hosts per-event per-channel notification preferences for the authenticated
 * user, grouped by settings category.
 */
import { NotificationPreferencesPanel } from "@/components/modules/settings/notification-preferences-panel";

/**
 * Render authenticated notification settings.
 */
export default function NotificationSettingsPage() {
  return (
    <main className="px-4 py-8 text-foreground md:px-8">
      <div className="mx-auto max-w-4xl">
        <header className="mb-6 rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm md:p-8">
          <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
            Notification settings
          </p>
          <h1 className="mt-2 font-heading text-3xl font-bold text-foreground md:text-4xl">
            Notifications
          </h1>
          <p className="mt-3 max-w-2xl text-sm leading-6 text-foreground-muted">
            Choose which marketplace events reach email and which stay in your
            in-app notification stream.
          </p>
        </header>
        <NotificationPreferencesPanel />
      </div>
    </main>
  );
}
