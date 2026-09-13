"use client";

/**
 * Admin user directory panel.
 *
 * Allows administrators to search users, filter by suspension state, and run
 * the suspend, unsuspend, and KYC-review mutations. Each is a sensitive
 * action: the API requires a step-up 2FA window, which the global step-up
 * prompt handles when the call is refused.
 * Styled as a responsive grid directory that functions as a table on desktop.
 */
import React, { useEffect, useMemo, useState } from "react";

import { AdminKycDocumentList } from "@/components/modules/admin/admin-kyc-document-list";
import { Button } from "@/components/ui/button";
import { authTokenStore } from "@/lib/auth/token-store";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import {
  listAdminUsersV1AdminUsersGet,
  reviewKycV1AdminUsersUserIdKycPatch,
  suspendUserV1AdminUsersUserIdSuspendPost,
  unsuspendUserV1AdminUsersUserIdUnsuspendPost,
} from "@/lib/generated/sdk.gen";
import { TableSkeleton } from "@/components/ui/skeletons/table-skeleton";
import type {
  AdminUserDirectoryItem,
  AdminUserDirectoryResponse,
} from "@/lib/generated/types.gen";
import { formatLabel } from "@/lib/marketplace/format";

type UserStatusFilter = "all" | "active" | "suspended" | "kyc_pending";
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
  const [currentUserId, setCurrentUserId] = useState<string | null>(null);
  const [kycReviewUserId, setKycReviewUserId] = useState<string | null>(null);
  const [kycNotes, setKycNotes] = useState("");
  const [kycBusy, setKycBusy] = useState(false);

  useEffect(() => {
    setCurrentUserId(authTokenStore.getState().userId);
  }, []);

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
      body: {},
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
    setSelectedUserId(null);
  }

  async function handleKycReview(
    userId: string,
    decision: "verified" | "rejected",
  ): Promise<void> {
    setKycBusy(true);
    setError(null);
    configureBrowserClient();
    const result = await reviewKycV1AdminUsersUserIdKycPatch({
      body: {
        status: decision,
        notes: kycNotes.trim() || null,
      },
      headers: getAccessTokenHeaders(),
      path: { user_id: userId },
    });
    setKycBusy(false);

    if (!result.response.ok || !result.data) {
      setError(describeGeneratedError(result.error));
      return;
    }

    setDirectory((current) => {
      if (!current) {
        return current;
      }
      // On the KYC-pending view the reviewed user no longer belongs; drop it.
      if (statusFilter === "kyc_pending") {
        return {
          ...current,
          items: current.items.filter((item) => item.user_id !== userId),
        };
      }
      return {
        ...current,
        items: current.items.map((item) =>
          item.user_id === userId ? { ...item, kyc_status: decision } : item,
        ),
      };
    });
    setKycNotes("");
    setKycReviewUserId(null);
  }

  if (loading) {
    return <TableSkeleton />;
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
          suspension controls.
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
            <option value="kyc_pending">KYC pending</option>
          </select>
        </label>
      </section>

      {error ? (
        <div className="rounded-2xl border border-error/30 bg-error/10 p-4 text-sm text-error">
          {error}
        </div>
      ) : null}

      <div className="grid gap-4 md:gap-0 md:divide-y md:divide-border-default/40 md:rounded-2xl md:border md:border-border-default md:bg-surface-1 md:shadow-sm overflow-hidden">
        {/* Table Header - Only visible on desktop/tablet */}
        <div className="hidden md:grid md:grid-cols-[1.5fr_1fr_1.2fr_0.8fr_1fr] md:gap-4 md:bg-surface-2/40 md:p-4 md:pl-6 md:pr-6 text-xs font-semibold uppercase tracking-wider text-foreground-muted select-none">
          <div>User</div>
          <div>Joined</div>
          <div>Roles</div>
          <div>Status</div>
          <div className="text-right">Actions</div>
        </div>

        {(directory?.items ?? []).map((item) => {
          const isSelected = selectedUserId === item.user_id;
          const isSelf = item.user_id === currentUserId;
          return (
            <article
              aria-label={item.display_name}
              className={`
                transition-colors flex flex-col
                /* Mobile Card styles */
                rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm gap-3
                /* Desktop/Tablet Table row styles */
                md:grid md:grid-cols-[1.5fr_1fr_1.2fr_0.8fr_1fr] md:items-center md:gap-4
                md:rounded-none md:border-none md:bg-transparent md:p-4 md:pl-6 md:pr-6 md:shadow-none
                ${isSelected ? "md:bg-surface-2/50" : "md:hover:bg-surface-2/30"}
              `}
              key={item.user_id}
              role="article"
            >
              {/* User Identity cell */}
              <div className="grid gap-0.5 md:col-span-1">
                <h3 className="font-heading text-lg font-bold text-foreground md:text-sm md:font-semibold flex items-center gap-1.5">
                  {item.display_name}
                  {isSelf ? (
                    <span className="rounded bg-accent/10 px-1.5 py-0.5 text-[9px] font-bold text-accent uppercase tracking-wide">
                      You
                    </span>
                  ) : null}
                </h3>
                <p className="text-sm text-foreground-muted md:text-xs">{item.email}</p>
                <span
                  className={[
                    "mt-1 inline-flex w-fit items-center rounded-md border px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wide",
                    item.kyc_status === "verified"
                      ? "border-success/30 bg-success/10 text-success"
                      : item.kyc_status === "pending"
                        ? "border-warning/30 bg-warning/10 text-warning"
                        : "border-border-default bg-surface-2 text-foreground-muted",
                  ].join(" ")}
                >
                  KYC: {item.kyc_status}
                </span>
              </div>

              {/* Joined Date cell */}
              <div className="text-sm text-foreground md:text-xs">
                <span className="md:hidden text-xs text-foreground-muted block mb-1 font-semibold uppercase tracking-wider">Joined</span>
                <span>{formatTimestamp(item.created_at)}</span>
              </div>

              {/* Roles Badge List cell */}
              <div>
                <span className="md:hidden text-xs text-foreground-muted block mb-1 font-semibold uppercase tracking-wider">Roles</span>
                <div className="flex flex-wrap gap-1">
                  {item.roles.map((role) => (
                    <span
                      className="inline-flex items-center rounded-md border border-border-default bg-surface-2 px-2 py-0.5 text-[10px] font-bold text-foreground-muted uppercase tracking-wide"
                      key={`${item.user_id}:${role}`}
                    >
                      {formatLabel(role)}
                    </span>
                  ))}
                </div>
              </div>

              {/* Status Pill cell */}
              <div>
                <span className="md:hidden text-xs text-foreground-muted block mb-1 font-semibold uppercase tracking-wider">Status</span>
                <span
                  className={[
                    "inline-flex items-center rounded-badge border px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wider",
                    item.suspended
                      ? "border-warning/30 bg-warning/10 text-warning"
                      : "border-success/30 bg-success/10 text-success",
                  ].join(" ")}
                >
                  {item.suspended ? "Suspended" : "Active"}
                </span>
              </div>

              {/* Action Buttons cell */}
              <div className="flex flex-wrap gap-2 md:justify-end">
                {item.kyc_status === "pending" ? (
                  <Button
                    onClick={() => {
                      setKycNotes("");
                      setKycReviewUserId(item.user_id);
                    }}
                    className="min-h-10 px-4"
                    variant="secondary"
                  >
                    Review KYC
                  </Button>
                ) : null}
                {item.is_superadmin ? (
                  <span className="inline-flex items-center rounded-badge border border-accent/30 bg-accent/10 px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wider text-accent">
                    Super admin
                  </span>
                ) : item.suspended ? (
                  <Button
                    onClick={() => setSelectedUserId(item.user_id)}
                    disabled={isSelf}
                    className="min-h-10 px-4"
                    variant="secondary"
                  >
                    Unsuspend
                  </Button>
                ) : (
                  <Button
                    onClick={() => setSelectedUserId(item.user_id)}
                    disabled={isSelf}
                    className="min-h-10 px-4"
                    variant="destructive"
                  >
                    Suspend
                  </Button>
                )}
              </div>

              {/* Expandable KYC review form */}
              {kycReviewUserId === item.user_id ? (
                <div className="mt-4 grid gap-4 rounded-xl border border-border-default bg-surface-2 p-4 col-span-full text-left">
                  {/* The documents come first: the decision below is about
                      them, and approving unlocks payouts. */}
                  <AdminKycDocumentList userId={item.user_id} />
                  <label className="grid gap-2 text-sm font-semibold text-foreground">
                    Notes (optional)
                    <textarea
                      className="min-h-24 rounded-xl border border-border-default bg-background px-4 py-3 text-sm text-foreground outline-none transition-colors focus-visible:ring-2 focus-visible:ring-accent"
                      onChange={(event) => setKycNotes(event.target.value)}
                      placeholder="Reason for rejection, or a note on approval"
                      value={kycNotes}
                    />
                  </label>
                  <div className="flex flex-wrap gap-3">
                    <Button
                      disabled={kycBusy}
                      onClick={() =>
                        void handleKycReview(item.user_id, "verified")
                      }
                    >
                      Approve KYC
                    </Button>
                    <Button
                      disabled={kycBusy}
                      onClick={() =>
                        void handleKycReview(item.user_id, "rejected")
                      }
                      variant="destructive"
                    >
                      Reject KYC
                    </Button>
                    <Button
                      onClick={() => {
                        setKycNotes("");
                        setKycReviewUserId(null);
                      }}
                      variant="secondary"
                    >
                      Cancel
                    </Button>
                  </div>
                </div>
              ) : null}

              {/* Expandable Suspension Form overlay (spans full width of the grid on desktop) */}
              {isSelected ? (
                <div className="mt-4 grid gap-4 rounded-xl border border-border-default bg-surface-2 p-4 col-span-full text-left">
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

                  <div className="flex flex-wrap gap-3">
                    {item.suspended ? (
                      <Button
                        disabled={pendingAction === "unsuspend"}
                        onClick={() => void handleUnsuspend()}
                      >
                        Confirm unsuspension
                      </Button>
                    ) : (
                      <Button
                        disabled={
                          pendingAction === "suspend" || reason.trim().length === 0
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
