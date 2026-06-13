/**
 * Unit coverage for the notification preferences settings panel.
 *
 * Verifies grouped category rendering, immediate-save per-channel toggles, and
 * locked critical-notification controls.
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { NotificationPreferencesPanel } from "@/components/modules/settings/notification-preferences-panel";
import {
  getNotificationPreferencesV1SettingsNotificationPreferencesGet,
  updateNotificationPreferencesV1SettingsNotificationPreferencesPatch,
} from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: () => "The request could not be completed.",
  getAccessTokenHeaders: () => ({ Authorization: "Bearer access-token" }),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  getNotificationPreferencesV1SettingsNotificationPreferencesGet: vi.fn(),
  updateNotificationPreferencesV1SettingsNotificationPreferencesPatch: vi.fn(),
}));

const matrix = {
  categories: [
    {
      category: "discovery",
      label: "Discovery",
      preferences: [
        {
          channels: [
            { channel: "email", enabled: true, locked: false },
            { channel: "in_app", enabled: true, locked: false },
          ],
          description: "Receive saved search alert updates.",
          label: "Saved Search Alert",
          notification_type: "saved_search_alert",
        },
      ],
    },
    {
      category: "financial",
      label: "Financial",
      preferences: [
        {
          channels: [
            { channel: "email", enabled: true, locked: true },
            { channel: "in_app", enabled: true, locked: true },
          ],
          description: "Receive dispute resolved release updates.",
          label: "Dispute Resolved Release",
          notification_type: "dispute_resolved_release",
        },
      ],
    },
  ],
};

describe("NotificationPreferencesPanel", () => {
  beforeEach(() => {
    vi.mocked(
      getNotificationPreferencesV1SettingsNotificationPreferencesGet,
    ).mockReset();
    vi.mocked(
      updateNotificationPreferencesV1SettingsNotificationPreferencesPatch,
    ).mockReset();
    vi.mocked(
      getNotificationPreferencesV1SettingsNotificationPreferencesGet,
    ).mockResolvedValue({
      data: matrix,
      error: undefined,
      response: new Response(null, { status: 200 }),
    });
  });

  it("loads grouped preferences, saves one toggle immediately, and locks critical rows", async () => {
    vi.mocked(
      updateNotificationPreferencesV1SettingsNotificationPreferencesPatch,
    ).mockResolvedValue({
      data: {
        categories: [
          {
            category: "discovery",
            label: "Discovery",
            preferences: [
              {
                channels: [
                  { channel: "email", enabled: false, locked: false },
                  { channel: "in_app", enabled: true, locked: false },
                ],
                description: "Receive saved search alert updates.",
                label: "Saved Search Alert",
                notification_type: "saved_search_alert",
              },
            ],
          },
          matrix.categories[1],
        ],
      },
      error: undefined,
      response: new Response(null, { status: 200 }),
    });

    render(<NotificationPreferencesPanel />);

    const discoveryRegion = await screen.findByRole("region", {
      name: /discovery notifications/i,
    });
    expect(
      within(discoveryRegion).getByRole("heading", {
        name: /saved search alert/i,
      }),
    ).toBeInTheDocument();

    const savedSearchEmailToggle = within(discoveryRegion).getByRole("checkbox", {
      name: /saved search alert email/i,
    });
    expect(savedSearchEmailToggle).toBeChecked();

    fireEvent.click(savedSearchEmailToggle);

    await waitFor(() => {
      expect(
        updateNotificationPreferencesV1SettingsNotificationPreferencesPatch,
      ).toHaveBeenCalledWith({
        body: {
          updates: [
            {
              channel: "email",
              enabled: false,
              notification_type: "saved_search_alert",
            },
          ],
        },
        headers: { Authorization: "Bearer access-token" },
      });
    });

    await waitFor(() => {
      expect(savedSearchEmailToggle).not.toBeChecked();
    });

    const financialRegion = await screen.findByRole("region", {
      name: /financial notifications/i,
    });
    const criticalEmailToggle = within(financialRegion).getByRole("checkbox", {
      name: /dispute resolved release email/i,
    });
    expect(criticalEmailToggle).toBeChecked();
    expect(criticalEmailToggle).toBeDisabled();
    expect(within(financialRegion).getByText(/always on/i)).toBeInTheDocument();
  });
});
