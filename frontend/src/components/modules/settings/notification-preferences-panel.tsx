"use client";

/**
 * Notification preferences settings panel.
 *
 * Renders the authenticated user's grouped notification preference matrix and
 * persists one event-channel toggle at a time through the generated settings
 * client.
 */
import { useEffect, useState } from "react";

import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import {
  getNotificationPreferencesV1SettingsNotificationPreferencesGet,
  updateNotificationPreferencesV1SettingsNotificationPreferencesPatch,
} from "@/lib/generated/sdk.gen";
import type {
  NotificationPreferenceCategory,
  NotificationPreferencesResponse,
} from "@/lib/generated/types.gen";

type PendingToggleKey = `${string}:${string}` | null;

/**
 * Convert API channel names into concise UI labels.
 *
 * @param channel - Raw channel identifier from the API.
 * @returns Human-readable label for the toggle column.
 */
function formatChannelLabel(channel: string): string {
  return channel === "in_app" ? "In-app" : "Email";
}

/**
 * Render grouped immediate-save notification preference controls.
 */
export function NotificationPreferencesPanel() {
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [matrix, setMatrix] = useState<NotificationPreferencesResponse | null>(null);
  const [pendingToggle, setPendingToggle] = useState<PendingToggleKey>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;

    async function loadPreferences(): Promise<void> {
      configureBrowserClient();
      const result = await getNotificationPreferencesV1SettingsNotificationPreferencesGet(
        {
          headers: getAccessTokenHeaders(),
        },
      );

      if (!mounted) {
        return;
      }

      setLoading(false);
      if (!result.response.ok || !result.data) {
        setError(describeGeneratedError(result.error));
        return;
      }

      setError(null);
      setMatrix(result.data);
    }

    void loadPreferences();
    return () => {
      mounted = false;
    };
  }, []);

  async function togglePreference(
    notificationType: string,
    channel: string,
    enabled: boolean,
  ): Promise<void> {
    const pendingKey = `${notificationType}:${channel}` as const;
    setPendingToggle(pendingKey);
    setError(null);
    setSuccessMessage(null);
    configureBrowserClient();

    const result = await updateNotificationPreferencesV1SettingsNotificationPreferencesPatch(
      {
        body: {
          updates: [
            {
              channel,
              enabled,
              notification_type: notificationType,
            },
          ],
        },
        headers: getAccessTokenHeaders(),
      },
    );
    setPendingToggle(null);

    if (!result.response.ok || !result.data) {
      setError(describeGeneratedError(result.error));
      return;
    }

    setMatrix(result.data);
    setSuccessMessage("Preferences updated.");
  }

  if (loading) {
    return (
      <p className="rounded-xl border border-border-default bg-surface-1 p-5 text-sm text-foreground-muted">
        Loading notification preferences...
      </p>
    );
  }

  return (
    <div className="space-y-4">
      {error ? (
        <p
          className="rounded-xl border border-error/30 bg-error/10 p-3 text-sm text-error"
          role="alert"
        >
          {error}
        </p>
      ) : null}
      {successMessage ? (
        <p
          className="rounded-xl border border-success/30 bg-success/10 p-3 text-sm text-success"
          role="status"
        >
          {successMessage}
        </p>
      ) : null}

      {matrix?.categories.map((category) => (
        <CategorySection
          category={category}
          key={category.category}
          onToggle={togglePreference}
          pendingToggle={pendingToggle}
        />
      ))}
    </div>
  );
}

type CategorySectionProps = {
  category: NotificationPreferenceCategory;
  onToggle: (
    notificationType: string,
    channel: string,
    enabled: boolean,
  ) => Promise<void>;
  pendingToggle: PendingToggleKey;
};

/**
 * Render one grouped settings category.
 *
 * @param props - Category data plus the immediate-save toggle handler.
 */
function CategorySection({
  category,
  onToggle,
  pendingToggle,
}: CategorySectionProps) {
  return (
    <section
      aria-label={`${category.label} notifications`}
      className="rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm"
      role="region"
    >
      <div className="mb-4">
        <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
          {category.label}
        </p>
        <h2 className="mt-2 font-heading text-xl font-bold text-foreground">
          {category.label} notifications
        </h2>
      </div>

      <div className="space-y-3">
        {category.preferences.map((preference) => (
          <article
            className="rounded-xl border border-border-default bg-surface-2 p-4"
            key={preference.notification_type}
          >
            <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <h3 className="font-heading text-base font-semibold text-foreground">
                    {preference.label}
                  </h3>
                  {preference.channels.some((channel) => channel.locked) ? (
                    <span className="rounded-md border border-success/30 bg-success/10 px-2 py-1 text-[11px] font-semibold uppercase tracking-[0.05em] text-success">
                      Always on
                    </span>
                  ) : null}
                </div>
                <p className="mt-2 max-w-2xl text-sm leading-6 text-foreground-muted">
                  {preference.description}
                </p>
              </div>

              <div className="grid gap-3 sm:grid-cols-2">
                {preference.channels.map((channel) => {
                  const toggleKey =
                    `${preference.notification_type}:${channel.channel}` as const;
                  const pending = pendingToggle === toggleKey;

                  return (
                    <label
                      className={[
                        "flex min-h-12 min-w-[168px] items-center justify-between gap-3 rounded-xl border px-4 py-3 text-sm",
                        channel.locked
                          ? "border-success/30 bg-success/10"
                          : "border-border-default bg-background hover:bg-surface-1",
                      ].join(" ")}
                      key={toggleKey}
                    >
                      <span className="font-medium text-foreground">
                        {formatChannelLabel(channel.channel)}
                      </span>
                      <input
                        aria-label={`${preference.label} ${formatChannelLabel(
                          channel.channel,
                        )}`}
                        checked={channel.enabled}
                        className="h-4 w-4 accent-accent"
                        disabled={channel.locked || pending}
                        onChange={(event) =>
                          void onToggle(
                            preference.notification_type,
                            channel.channel,
                            event.target.checked,
                          )
                        }
                        type="checkbox"
                      />
                    </label>
                  );
                })}
              </div>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
