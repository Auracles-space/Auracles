"use client";

/**
 * Interactive notification dropdown component.
 *
 * Fetches user notifications via generated SDK, supports marking individual
 * notifications as read (PATCH), and marking all as read (POST). Styled to match
 * the project's Bento Box design guidelines.
 */
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import {
  listNotificationsV1NotificationsGet,
  markAllNotificationsReadV1NotificationsReadAllPost,
  markNotificationReadV1NotificationsNotificationIdReadPatch,
} from "@/lib/generated/sdk.gen";
import type { NotificationItem } from "@/lib/generated/types.gen";

/**
 * Formats a timestamp as a relative date/time string.
 *
 * @param dateString - ISO date string to format.
 */
function formatRelativeTime(dateString: string): string {
  try {
    const date = new Date(dateString);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffSecs = Math.floor(diffMs / 1000);
    const diffMins = Math.floor(diffSecs / 60);
    const diffHours = Math.floor(diffMins / 60);
    const diffDays = Math.floor(diffHours / 24);

    if (diffSecs < 60) return "just now";
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    if (diffDays < 7) return `${diffDays}d ago`;
    return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  } catch {
    return "";
  }
}

/**
 * Render an interactive notification dropdown/popover menu.
 */
export function NotificationDropdown() {
  const router = useRouter();
  const [isOpen, setIsOpen] = useState(false);
  const [notifications, setNotifications] = useState<NotificationItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [markingAllRead, setMarkingAllRead] = useState(false);

  const triggerRef = useRef<HTMLButtonElement>(null);
  const popoverRef = useRef<HTMLDivElement>(null);

  // Load notifications
  const fetchNotifications = async (quiet = false) => {
    if (!quiet) setLoading(true);
    configureBrowserClient();
    try {
      const result = await listNotificationsV1NotificationsGet({
        headers: getAccessTokenHeaders(),
        query: { page: 1, page_size: 20, unread_only: false },
      });

      if (result.response.ok && result.data) {
        setNotifications(result.data.notifications);
      }
    } catch {
      console.error("Failed to load notifications");
    } finally {
      if (!quiet) setLoading(false);
    }
  };

  // Initial load and polling setup
  useEffect(() => {
    void fetchNotifications();

    const interval = setInterval(() => {
      void fetchNotifications(true);
    }, 60000); // Poll every 60 seconds

    return () => clearInterval(interval);
  }, []);

  // Click outside listener to close popover
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (
        popoverRef.current &&
        !popoverRef.current.contains(event.target as Node) &&
        triggerRef.current &&
        !triggerRef.current.contains(event.target as Node)
      ) {
        setIsOpen(false);
      }
    }

    if (isOpen) {
      document.addEventListener("mousedown", handleClickOutside);
    }
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, [isOpen]);

  const unreadCount = notifications.filter((n) => !n.read_at).length;

  // Mark a single notification as read (PATCH)
  const handleItemClick = async (item: NotificationItem) => {
    if (!item.read_at) {
      // Optimistically update UI
      setNotifications((prev) =>
        prev.map((n) =>
          n.id === item.id ? { ...n, read_at: new Date().toISOString() } : n
        )
      );

      configureBrowserClient();
      await markNotificationReadV1NotificationsNotificationIdReadPatch({
        headers: getAccessTokenHeaders(),
        path: { notification_id: item.id },
      }).catch((err: unknown) => {
        console.error("Failed to mark notification as read", err);
        // Re-fetch on failure to sync
        void fetchNotifications(true);
      });
    }

    // Navigate if link exists
    if (item.link) {
      router.push(item.link);
      setIsOpen(false);
    }
  };

  // Mark all notifications as read (POST)
  const handleMarkAllRead = async () => {
    setMarkingAllRead(true);
    // Optimistically update UI
    setNotifications((prev) =>
      prev.map((n) => (!n.read_at ? { ...n, read_at: new Date().toISOString() } : n))
    );

    configureBrowserClient();
    try {
      const result = await markAllNotificationsReadV1NotificationsReadAllPost({
        headers: getAccessTokenHeaders(),
      });
      if (!result.response.ok) {
        console.error(describeGeneratedError(result.error));
        // Re-fetch on failure to sync
        void fetchNotifications(true);
      }
    } catch {
      console.error("Failed to mark all notifications as read");
      void fetchNotifications(true);
    } finally {
      setMarkingAllRead(false);
    }
  };

  return (
    <div className="relative">
      <button
        ref={triggerRef}
        onClick={() => setIsOpen(!isOpen)}
        className="relative flex h-10 w-10 items-center justify-center rounded-xl border border-border-default bg-surface-1 shadow-sm text-foreground-muted outline-none transition-all hover:bg-surface-2 focus-visible:ring-2 focus-visible:ring-accent"
        aria-label="Toggle notifications menu"
        aria-expanded={isOpen}
      >
        <svg className="h-4 w-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9"
          />
        </svg>
        {unreadCount > 0 && (
          <span className="absolute top-2.5 right-2.5 flex h-2 w-2">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-accent opacity-75"></span>
            <span className="relative inline-flex h-2 w-2 rounded-full bg-accent"></span>
          </span>
        )}
      </button>

      {isOpen && (
        <div
          ref={popoverRef}
          className="absolute right-0 top-12 z-50 w-80 rounded-2xl border border-border-default bg-surface-1 p-4 shadow-[0_4px_20px_rgba(0,0,0,0.08)] md:shadow-bento"
        >
          <div className="flex items-center justify-between border-b border-border-default pb-2.5 mb-3">
            <h3 className="text-sm font-semibold text-foreground">Notifications</h3>
            {unreadCount > 0 && (
              <button
                onClick={() => void handleMarkAllRead()}
                disabled={markingAllRead}
                className="text-xs font-medium text-accent hover:underline disabled:opacity-50"
              >
                {markingAllRead ? "Marking..." : "Mark all as read"}
              </button>
            )}
          </div>

          <div className="max-h-[360px] overflow-y-auto space-y-2 pr-1">
            {loading ? (
              <p className="text-center py-6 text-sm text-foreground-muted">Loading notifications...</p>
            ) : notifications.length === 0 ? (
              <p className="text-center py-6 text-sm text-foreground-muted">No notifications</p>
            ) : (
              notifications.map((item) => (
                <div
                  key={item.id}
                  onClick={() => void handleItemClick(item)}
                  className={`group relative flex flex-col gap-1 rounded-xl p-3 border border-transparent transition-colors cursor-pointer text-left ${
                    !item.read_at
                      ? "bg-surface-2 hover:bg-surface-3 border-border-default"
                      : "hover:bg-surface-2"
                  }`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <p className={`text-sm font-semibold text-foreground pr-4 ${!item.read_at ? "" : "font-normal"}`}>
                      {item.title}
                    </p>
                    {!item.read_at && (
                      <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-accent" />
                    )}
                  </div>
                  <p className="text-xs text-foreground-muted leading-relaxed">
                    {item.body}
                  </p>
                  <p className="text-[10px] text-foreground-muted mt-0.5">
                    {formatRelativeTime(item.created_at)}
                  </p>
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}
