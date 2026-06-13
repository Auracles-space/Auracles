"use client";

/**
 * Admin user directory panel.
 *
 * Allows administrators to search users, filter by suspension state, and run
 * the suspend or unsuspend mutations with TOTP confirmation.
 */
import { useEffect, useMemo, useState } from "react";

import { TotpInput } from "@/components/modules/auth/totp-input";
import { Button } from "@/components/ui/button";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import {
  listAdminUsersV1AdminUsersGet,
  suspendUserV1AdminUsersUserIdSuspendPost,
  unsuspendUserV1AdminUsersUserIdUnsuspendPost,
} from "@/lib/generated/sdk.gen";
import type {
  AdminUserDirectoryItem,
  AdminUserDirectoryResponse,
} from "@/lib/generated/types.gen";
import { formatLabel } from "@/lib/marketplace/format";

type UserStatusFilter = "all" | "active" | "suspended";
type PendingAction = "suspend" | "unsuspend" | null;

/**
 * Format one user creation timestamp for compact admin copy.
 *
 * @param value - API timestamp string.
 */
function formatTimestamp(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(parsed);
}

/**
 * Replace one row in a directory response after a mutation.
 *
 * @param current - Current directory payload.
 * @param updated - Updated row for one user.
 */
function replaceDirectoryRow(
  current: AdminUserDirectoryResponse | null,
  updated: AdminUserDirectoryItem,
): AdminUserDirectoryResponse | null {
  if (!current) {
    return current;
  }
  return {
    ...current,
    items: current.items.map((item) =>
      item.user_id === updated.user_id ? updated : item,
    ),
  };
}

/**
 * Render user search and suspension controls for admins.
 */
export function AdminUserDirectoryPanel() {
  const [directory, setDirectory] = useState<AdminUserDirectoryResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [pendingAction, setPendingAction] = useState<PendingAction>(null);
  const [query, setQuery] = useState("");
  const [reason, setReason] = useState("");
  const [selectedUserId, setSelectedUserId] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<UserStatusFilter>("all");
  const [totpCode, setTotpCode] = useState("");

  const selectedUser = useMemo(
    () =>
      directory?.items.find((item) => item.user_id === selectedUserId) ?? null,
    [directory?.items, selectedUserId],
  );

  useEffect(() => {
    let mounted = true;

    async function loadUsers(): Promise<void> {
      configureBrowserClient();
      const result = await listAdminUsersV1AdminUsersGet({
        headers: getAccessTokenHeaders(),
        query: {
          page: 1,
          page_size: 20,
          query: query.trim() || undefined,
          status: statusFilter,
        },
      });

      if (!mounted) {
        return;
      }

      setLoading(false);
      if (!result.response.ok || !result.data) {
        setError(describeGeneratedError(result.error));
        return;
      }

      setError(null);
      setDirectory(result.data);
    }

    void loadUsers();
    return () => {
      mounted = false;
    };
  }, [query, statusFilter]);

  async function handleSuspend(): Promise<void> {
    if (!selectedUser) {
      return;
    }

    setPendingAction("suspend");
    setError(null);
    configureBrowserClient();
    const result = await suspendUserV1AdminUsersUserIdSuspendPost({
      body: {
        reason: reason.trim(),
        totp_code: totpCode.trim(),
      },
      headers: getAccessTokenHeaders(),
      path: { user_id: selectedUser.user_id },
    });
    setPendingAction(null);

    if (!result.response.ok || !result.data) {
      setError(describeGeneratedError(result.error));
      return;
    }

    setDirectory((current) =>
      replaceDirectoryRow(current, {
        ...selectedUser,
        suspended: true,
        suspended_at: result.data.suspended_at,
      }),
    );
    setReason("");
    setTotpCode("");
    setSelectedUserId(null);
  }

  async function handleUnsuspend(): Promise<void> {
    if (!selectedUser) {
      return;
    }

    setPendingAction("unsuspend");
    setError(null);
    configureBrowserClient();
    const result = await unsuspendUserV1AdminUsersUserIdUnsuspendPost({
      body: {
        totp_code: totpCode.trim(),
      },
      headers: getAccessTokenHeaders(),
      path: { user_id: selectedUser.user_id },
    });
    setPendingAction(null);

    if (!result.response.ok || !result.data) {
      setError(describeGeneratedError(result.error));
      return;
    }

    setDirectory((current) =>
      replaceDirectoryRow(current, {
        ...selectedUser,
        suspended: false,
        suspended_at: null,
      }),
    );
    setTotpCode("");
    setSelectedUserId(null);
  }

  if (loading) {
    return <p className="text-sm text-foreground-muted">Loading user controls.</p>;
  }

  return (
    <section className="grid gap-6">
      <header className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
        <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
          Admin users
        </p>
        <h2 className="mt-2 font-heading text-3xl font-bold text-foreground">
          User controls
        </h2>
        <p className="mt-3 max-w-3xl text-sm leading-6 text-foreground-muted">
          Search accounts, inspect approved roles, and apply reversible
          suspension controls with 2FA confirmation.
        </p>
      </header>

      <section className="grid gap-4 rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm md:grid-cols-[minmax(0,1fr)_220px]">
        <label className="grid gap-2 text-sm font-semibold text-foreground">
          Search users
          <input
            className="min-h-12 rounded-xl border border-border-default bg-background px-4 text-sm text-foreground outline-none transition-colors focus-visible:ring-2 focus-visible:ring-accent"
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search display name or email"
            value={query}
          />
        </label>
        <label className="grid gap-2 text-sm font-semibold text-foreground">
          Status
          <select
            className="min-h-12 rounded-xl border border-border-default bg-background px-4 text-sm text-foreground outline-none transition-colors focus-visible:ring-2 focus-visible:ring-accent"
            onChange={(event) =>
              setStatusFilter(event.target.value as UserStatusFilter)
            }
            value={statusFilter}
          >
            <option value="all">All users</option>
            <option value="active">Active only</option>
            <option value="suspended">Suspended only</option>
          </select>
        </label>
      </section>

      {error ? (
        <div className="rounded-2xl border border-error/30 bg-error/10 p-4 text-sm text-error">
          {error}
        </div>
      ) : null}

      <div className="grid gap-4">
        {(directory?.items ?? []).map((item) => {
          const isSelected = selectedUserId === item.user_id;
          return (
            <article
              aria-label={item.display_name}
              className="rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm"
              key={item.user_id}
              role="article"
            >
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h3 className="font-heading text-xl font-bold text-foreground">
                    {item.display_name}
                  </h3>
                  <p className="mt-1 text-sm text-foreground">{item.email}</p>
                  <p className="mt-1 text-sm text-foreground-muted">
                    Joined {formatTimestamp(item.created_at)}
                  </p>
                </div>
                <span
                  className={[
                    "rounded-md border px-2.5 py-1 text-xs font-semibold uppercase tracking-[0.05em]",
                    item.suspended
                      ? "border-warning/30 bg-warning/10 text-warning"
                      : "border-success/30 bg-success/10 text-success",
                  ].join(" ")}
                >
                  {item.suspended ? "Suspended" : "Active"}
                </span>
              </div>

              <div className="mt-4 flex flex-wrap gap-2">
                {item.roles.map((role) => (
                  <span
                    className="rounded-md border border-border-default bg-surface-2 px-2.5 py-1 text-xs text-foreground"
                    key={`${item.user_id}:${role}`}
                  >
                    {formatLabel(role)}
                  </span>
                ))}
              </div>

              <div className="mt-4 flex flex-wrap gap-3">
                {item.suspended ? (
                  <Button onClick={() => setSelectedUserId(item.user_id)} variant="secondary">
                    Unsuspend
                  </Button>
                ) : (
                  <Button onClick={() => setSelectedUserId(item.user_id)} variant="destructive">
                    Suspend
                  </Button>
                )}
              </div>

              {isSelected ? (
                <div className="mt-5 grid gap-4 rounded-xl border border-border-default bg-surface-2 p-4">
                  {!item.suspended ? (
                    <label className="grid gap-2 text-sm font-semibold text-foreground">
                      Reason
                      <textarea
                        className="min-h-28 rounded-xl border border-border-default bg-background px-4 py-3 text-sm text-foreground outline-none transition-colors focus-visible:ring-2 focus-visible:ring-accent"
                        onChange={(event) => setReason(event.target.value)}
                        value={reason}
                      />
                    </label>
                  ) : null}

                  <TotpInput onChange={setTotpCode} value={totpCode} />

                  <div className="flex flex-wrap gap-3">
                    {item.suspended ? (
                      <Button
                        disabled={pendingAction === "unsuspend" || totpCode.trim().length < 6}
                        onClick={() => void handleUnsuspend()}
                      >
                        Confirm unsuspension
                      </Button>
                    ) : (
                      <Button
                        disabled={
                          pendingAction === "suspend" ||
                          reason.trim().length === 0 ||
                          totpCode.trim().length < 6
                        }
                        onClick={() => void handleSuspend()}
                        variant="destructive"
                      >
                        Confirm suspension
                      </Button>
                    )}
                    <Button
                      onClick={() => {
                        setReason("");
                        setSelectedUserId(null);
                        setTotpCode("");
                      }}
                      variant="secondary"
                    >
                      Cancel
                    </Button>
                  </div>
                </div>
              ) : null}
            </article>
          );
        })}
      </div>
    </section>
  );
}
