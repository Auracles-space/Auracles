import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { NotificationDropdown } from "@/components/modules/layout/notification-dropdown";
import {
  listNotificationsV1NotificationsGet,
  markAllNotificationsReadV1NotificationsReadAllPost,
  markNotificationReadV1NotificationsNotificationIdReadPatch,
} from "@/lib/generated/sdk.gen";

const pushMock = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: pushMock,
  }),
}));

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: (error: { detail?: string } | undefined) =>
    error?.detail ?? "The request could not be completed.",
  getAccessTokenHeaders: () => ({ Authorization: "Bearer access-token" }),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  client: { setConfig: vi.fn() },
  listNotificationsV1NotificationsGet: vi.fn(),
  markAllNotificationsReadV1NotificationsReadAllPost: vi.fn(),
  markNotificationReadV1NotificationsNotificationIdReadPatch: vi.fn(),
}));

const mockNotifications = [
  {
    id: "notif-1",
    type: "info",
    title: "Milestone Funded",
    body: "Milestone 1 for your project has been funded.",
    link: "/projects/project-123",
    payload: null,
    read_at: null,
    created_at: new Date(Date.now() - 60000).toISOString(), // 1m ago
  },
  {
    id: "notif-2",
    type: "warning",
    title: "Role Assigned",
    body: "You have been assigned the Attestor role.",
    link: null,
    payload: null,
    read_at: "2026-06-16T08:00:00Z",
    created_at: new Date(Date.now() - 3600000).toISOString(), // 1h ago
  },
];

describe("NotificationDropdown", () => {
  beforeEach(() => {
    vi.mocked(listNotificationsV1NotificationsGet).mockReset();
    vi.mocked(markAllNotificationsReadV1NotificationsReadAllPost).mockReset();
    vi.mocked(markNotificationReadV1NotificationsNotificationIdReadPatch).mockReset();
    pushMock.mockReset();
  });

  it("renders trigger button and fetches notifications on mount", async () => {
    vi.mocked(listNotificationsV1NotificationsGet).mockResolvedValue({
      data: { notifications: mockNotifications },
      error: undefined,
      response: new Response(null, { status: 200 }),
    });

    render(<NotificationDropdown />);

    // Unread count is 1, so badge dot should be present
    await waitFor(() => {
      expect(listNotificationsV1NotificationsGet).toHaveBeenCalled();
    });

    // Check bell icon is present
    const bellBtn = screen.getByRole("button", { name: /toggle notifications menu/i });
    expect(bellBtn).toBeInTheDocument();
  });

  it("toggles the dropdown popover and displays notifications", async () => {
    vi.mocked(listNotificationsV1NotificationsGet).mockResolvedValue({
      data: { notifications: mockNotifications },
      error: undefined,
      response: new Response(null, { status: 200 }),
    });

    render(<NotificationDropdown />);

    await waitFor(() => {
      expect(listNotificationsV1NotificationsGet).toHaveBeenCalled();
    });

    // Open dropdown
    const bellBtn = screen.getByRole("button", { name: /toggle notifications menu/i });
    fireEvent.click(bellBtn);

    // Header and list items should be shown
    expect(screen.getByText("Notifications")).toBeInTheDocument();
    expect(screen.getByText("Milestone Funded")).toBeInTheDocument();
    expect(screen.getByText("Role Assigned")).toBeInTheDocument();
    expect(screen.getByText("Milestone 1 for your project has been funded.")).toBeInTheDocument();
  });

  it("marks all notifications as read when clicking Mark all as read", async () => {
    vi.mocked(listNotificationsV1NotificationsGet).mockResolvedValue({
      data: { notifications: mockNotifications },
      error: undefined,
      response: new Response(null, { status: 200 }),
    });

    vi.mocked(markAllNotificationsReadV1NotificationsReadAllPost).mockResolvedValue({
      data: { updated_count: 1 },
      error: undefined,
      response: new Response(null, { status: 200 }),
    });

    render(<NotificationDropdown />);

    await waitFor(() => {
      expect(listNotificationsV1NotificationsGet).toHaveBeenCalled();
    });

    // Open dropdown
    fireEvent.click(screen.getByRole("button", { name: /toggle notifications menu/i }));

    const markAllBtn = screen.getByRole("button", { name: /mark all as read/i });
    fireEvent.click(markAllBtn);

    expect(markAllNotificationsReadV1NotificationsReadAllPost).toHaveBeenCalled();

    // Verify optimistic UI update (the unread indicator bg/dot should be cleared)
    await waitFor(() => {
      // The mark all as read button should disappear once all are read
      expect(screen.queryByRole("button", { name: /mark all as read/i })).not.toBeInTheDocument();
    });
  });

  it("marks single notification as read on click and navigates if link exists", async () => {
    vi.mocked(listNotificationsV1NotificationsGet).mockResolvedValue({
      data: { notifications: mockNotifications },
      error: undefined,
      response: new Response(null, { status: 200 }),
    });

    vi.mocked(markNotificationReadV1NotificationsNotificationIdReadPatch).mockResolvedValue({
      data: { ...mockNotifications[0], read_at: new Date().toISOString() },
      error: undefined,
      response: new Response(null, { status: 200 }),
    });

    render(<NotificationDropdown />);

    await waitFor(() => {
      expect(listNotificationsV1NotificationsGet).toHaveBeenCalled();
    });

    // Open dropdown
    fireEvent.click(screen.getByRole("button", { name: /toggle notifications menu/i }));

    // Click on unread item
    const unreadItem = screen.getByText("Milestone Funded");
    fireEvent.click(unreadItem);

    // Expect PATCH call and Router push to have been triggered
    await waitFor(() => {
      expect(markNotificationReadV1NotificationsNotificationIdReadPatch).toHaveBeenCalledWith({
        headers: { Authorization: "Bearer access-token" },
        path: { notification_id: "notif-1" },
      });
      expect(pushMock).toHaveBeenCalledWith("/projects/project-123");
    });
  });
});
