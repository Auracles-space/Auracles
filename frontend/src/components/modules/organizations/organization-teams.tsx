"use client";

/**
 * Organization Teams management panel.
 *
 * Lets admins and owners create, rename, and delete subgroups (teams)
 * within the organization. Read is restricted to admin/owner via the
 * `useOrganization` context; the backend enforces the same constraint.
 *
 * Maps to: FR-ORG-017 through FR-ORG-019.
 */
import { useEffect, useState } from "react";
import {
  createTeamV1OrgsOrgIdTeamsPost,
  deleteTeamV1OrgsOrgIdTeamsTeamIdDelete,
  disableTeamCapabilityV1OrgsOrgIdTeamsTeamIdCapabilitiesCapabilityDelete,
  enableTeamCapabilityV1OrgsOrgIdTeamsTeamIdCapabilitiesCapabilityPut,
  listTeamsV1OrgsOrgIdTeamsGet,
  renameTeamV1OrgsOrgIdTeamsTeamIdPatch,
} from "@/lib/generated/sdk.gen";
import type { OrgTeamResponse } from "@/lib/generated/types.gen";
import { describeGeneratedError, getAccessTokenHeaders } from "@/lib/auth/form-client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { useToast } from "@/components/ui/toast";
import { useOrganization } from "./organization-context";
import { TeamMemberManager } from "./team-member-manager";
import {
  TeamCapabilityToggles,
  type TeamCapabilityKey,
} from "./team-capability-toggles";
import {
  ChevronDownIcon,
  Pencil1Icon,
  PersonIcon,
  PlusIcon,
  TrashIcon,
} from "@radix-ui/react-icons";

type PendingTeamCapabilityAction = {
  teamId: string;
  teamName: string;
  capability: TeamCapabilityKey;
  enabled: boolean;
};

/**
 * Render the create-team form and the team list with roster and capability
 * controls.
 */
export function OrganizationTeams() {
  const { orgId, role, isSuspended, capabilities, refreshOrganization } =
    useOrganization();
  const isAdmin = role === "admin" || role === "owner";
  const toast = useToast();

  const [teams, setTeams] = useState<OrgTeamResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Create state
  const [newTeamName, setNewTeamName] = useState("");
  const [createLoading, setCreateLoading] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  // Edit state
  const [editingTeam, setEditingTeam] = useState<OrgTeamResponse | null>(null);
  const [editName, setEditName] = useState("");
  const [editLoading, setEditLoading] = useState(false);
  const [editError, setEditError] = useState<string | null>(null);

  // Expanded roster state — id of the team whose members are being managed.
  const [expandedTeamId, setExpandedTeamId] = useState<string | null>(null);

  // Delete state
  const [teamToDelete, setTeamToDelete] = useState<OrgTeamResponse | null>(null);
  const [deleteLoading, setDeleteLoading] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  // Capability toggle state
  const [pendingCapabilityAction, setPendingCapabilityAction] =
    useState<PendingTeamCapabilityAction | null>(null);
  const [capabilityLoading, setCapabilityLoading] = useState(false);
  const [capabilityError, setCapabilityError] = useState<string | null>(null);

  async function loadTeams() {
    if (!isAdmin) {
      setLoading(false);
      return;
    }

    try {
      const result = await listTeamsV1OrgsOrgIdTeamsGet({
        path: { org_id: orgId },
        headers: getAccessTokenHeaders(),
      });
      if (result.response.ok && result.data) {
        setTeams(result.data.teams);
      } else {
        setError(describeGeneratedError(result.error));
      }
    } catch {
      setError("An error occurred loading teams.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadTeams();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orgId, isAdmin]);

  function openCapabilityConfirm(
    team: OrgTeamResponse,
    capability: TeamCapabilityKey,
    enabled: boolean,
  ) {
    setCapabilityError(null);
    setPendingCapabilityAction({
      teamId: team.id,
      teamName: team.name,
      capability,
      enabled,
    });
  }

  function closeCapabilityConfirm() {
    if (capabilityLoading) {
      return;
    }
    setCapabilityError(null);
    setPendingCapabilityAction(null);
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!isAdmin || isSuspended) return;

    setCreateLoading(true);
    setCreateError(null);

    try {
      const result = await createTeamV1OrgsOrgIdTeamsPost({
        path: { org_id: orgId },
        body: { name: newTeamName },
        headers: getAccessTokenHeaders(),
      });

      if (!result.response.ok) {
        setCreateError(describeGeneratedError(result.error));
      } else {
        setNewTeamName("");
        await loadTeams();
      }
    } catch {
      setCreateError("Unexpected error occurred while creating team.");
    } finally {
      setCreateLoading(false);
    }
  }

  async function handleEditSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!isAdmin || !editingTeam || isSuspended) return;

    setEditLoading(true);
    setEditError(null);

    try {
      const result = await renameTeamV1OrgsOrgIdTeamsTeamIdPatch({
        path: { org_id: orgId, team_id: editingTeam.id },
        body: { name: editName },
        headers: getAccessTokenHeaders(),
      });

      if (!result.response.ok) {
        setEditError(describeGeneratedError(result.error));
        setEditLoading(false);
      } else {
        setEditingTeam(null);
        setEditLoading(false);
        await loadTeams();
      }
    } catch {
      setEditError("Unexpected error occurred.");
      setEditLoading(false);
    }
  }

  async function handleDelete() {
    if (!isAdmin || !teamToDelete || isSuspended) return;

    setDeleteLoading(true);
    setDeleteError(null);

    try {
      const result = await deleteTeamV1OrgsOrgIdTeamsTeamIdDelete({
        path: { org_id: orgId, team_id: teamToDelete.id },
        headers: getAccessTokenHeaders(),
      });

      if (!result.response.ok) {
        setDeleteError(describeGeneratedError(result.error));
        setDeleteLoading(false);
        setTeamToDelete(null);
      } else {
        setTeamToDelete(null);
        setDeleteLoading(false);
        await loadTeams();
      }
    } catch {
      setDeleteError("Unexpected error occurred while deleting team.");
      setDeleteLoading(false);
      setTeamToDelete(null);
    }
  }

  async function handleConfirmCapabilityAction() {
    if (!pendingCapabilityAction) {
      return;
    }

    setCapabilityLoading(true);
    setCapabilityError(null);

    try {
      const result = pendingCapabilityAction.enabled
        ? await disableTeamCapabilityV1OrgsOrgIdTeamsTeamIdCapabilitiesCapabilityDelete(
            {
              path: {
                org_id: orgId,
                team_id: pendingCapabilityAction.teamId,
                capability: pendingCapabilityAction.capability,
              },
              headers: getAccessTokenHeaders(),
            },
          )
        : await enableTeamCapabilityV1OrgsOrgIdTeamsTeamIdCapabilitiesCapabilityPut({
            path: {
              org_id: orgId,
              team_id: pendingCapabilityAction.teamId,
              capability: pendingCapabilityAction.capability,
            },
            headers: getAccessTokenHeaders(),
          });

      if (!result.response.ok) {
        setCapabilityError(describeGeneratedError(result.error));
        return;
      }

      await refreshOrganization();
      await loadTeams();
      toast.success(
        `${pendingCapabilityAction.capability[0].toUpperCase()}${pendingCapabilityAction.capability.slice(1)} updated for ${pendingCapabilityAction.teamName}.`,
      );
      setPendingCapabilityAction(null);
    } catch {
      setCapabilityError("Unexpected error occurred while updating the team.");
    } finally {
      setCapabilityLoading(false);
    }
  }

  if (!isAdmin) {
    return (
      <div className="rounded-2xl border border-error/50 bg-error/5 p-6 text-center text-error">
        You do not have permission to view this page.
      </div>
    );
  }

  if (loading) {
    return (
      <div className="flex h-32 items-center justify-center">
        <Spinner className="h-6 w-6 text-accent" />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6 max-w-4xl">

      {/* ── Create Team Card ─────────────────────────────── */}
      <div className="overflow-hidden rounded-3xl border border-border-default bg-surface-1 shadow-sm transition hover:shadow-bento">
        {/* Header strip */}
        <div className="border-b border-border-default bg-surface-2/50 px-8 py-5">
          <p className="text-xs font-semibold uppercase tracking-[0.08em] text-accent">
            New team
          </p>
          <h2 className="mt-0.5 font-heading text-xl font-bold text-foreground">
            Create a team
          </h2>
          <p className="mt-1 text-sm text-foreground-muted">
            Teams let you group members and assign roles within your organization.
          </p>
        </div>

        <div className="px-8 py-6">
          {createError && (
            <div className="mb-5 rounded-xl border border-error/40 bg-error/5 px-4 py-3 text-sm text-error">
              {createError}
            </div>
          )}
          <form onSubmit={handleCreate} className="flex flex-col gap-4 sm:flex-row sm:items-end">
            <div className="flex-1">
              <label htmlFor="teamName" className="mb-1.5 block text-sm font-semibold text-foreground">
                Team name <span className="text-error">*</span>
              </label>
              <Input
                id="teamName"
                required
                disabled={isSuspended}
                value={newTeamName}
                onChange={(e) => setNewTeamName(e.target.value)}
                placeholder="e.g. Engineering, Design, Legal…"
                className="rounded-xl bg-background shadow-sm"
              />
            </div>
            <Button
              type="submit"
              loading={createLoading}
              disabled={isSuspended || !newTeamName.trim()}
              className="w-full shrink-0 sm:w-auto"
            >
              Create team
            </Button>
          </form>
        </div>
      </div>

      {/* ── Teams List Card ───────────────────────────────── */}
      <div className="overflow-hidden rounded-3xl border border-border-default bg-surface-1 shadow-sm transition hover:shadow-bento">
        {/* Header */}
        <div className="border-b border-border-default bg-surface-2/50 px-8 py-5">
          <div className="flex items-center justify-between gap-4">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.08em] text-accent">
                Organisation
              </p>
              <h2 className="mt-0.5 font-heading text-xl font-bold text-foreground">
                Teams
              </h2>
              <p className="mt-1 text-sm text-foreground-muted">
                Subgroups within your organization.
              </p>
            </div>
            {teams.length > 0 && (
              <span className="inline-flex shrink-0 items-center whitespace-nowrap rounded-badge border border-border-default bg-surface-2 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.05em] text-foreground-muted">
                {teams.length} {teams.length === 1 ? "team" : "teams"}
              </span>
            )}
          </div>
        </div>

        {/* Errors */}
        {(error || editError || deleteError) && (
          <div className="mx-6 mt-6 rounded-xl border border-error/40 bg-error/5 px-4 py-3 text-sm text-error">
            {error || editError || deleteError}
          </div>
        )}

        {/* Empty state */}
        {teams.length === 0 ? (
          <div className="flex flex-col items-center justify-center gap-3 px-8 py-16 text-center">
            <div className="flex h-14 w-14 items-center justify-center rounded-2xl border border-border-default bg-surface-2">
              <PersonIcon className="h-6 w-6 text-foreground-muted" />
            </div>
            <div>
              <p className="font-semibold text-foreground">No teams yet</p>
              <p className="mt-1 text-sm text-foreground-muted">
                Create your first team above to start grouping members.
              </p>
            </div>
          </div>
        ) : (
          <ul className="divide-y divide-border-default">
            {teams.map((team) => (
              <li key={team.id} className="flex flex-col">
               <div className="flex flex-col gap-4 px-8 py-5 transition-colors hover:bg-surface-2/50 sm:flex-row sm:items-center sm:justify-between">
                {editingTeam?.id === team.id ? (
                  /* ── Inline edit form ── */
                  <form
                    onSubmit={handleEditSubmit}
                    className="flex flex-1 flex-wrap items-center gap-3"
                  >
                    <Input
                      autoFocus
                      disabled={editLoading || isSuspended}
                      value={editName}
                      onChange={(e) => setEditName(e.target.value)}
                      className="max-w-xs rounded-xl bg-background shadow-sm"
                    />
                    <div className="flex gap-2">
                      <Button
                        type="submit"
                        loading={editLoading}
                        disabled={isSuspended || !editName.trim()}
                        className="min-h-11 px-5 text-sm"
                      >
                        Save
                      </Button>
                      <Button
                        type="button"
                        variant="secondary"
                        className="min-h-11 px-5 text-sm"
                        onClick={() => setEditingTeam(null)}
                      >
                        Cancel
                      </Button>
                    </div>
                  </form>
                ) : (
                  <>
                    <div className="flex-1">
                      {/* ── Team info (toggles the member roster) ── */}
                      <button
                        type="button"
                        onClick={() =>
                          setExpandedTeamId((prev) =>
                            prev === team.id ? null : team.id,
                          )
                        }
                        aria-expanded={expandedTeamId === team.id}
                        className="flex min-h-11 w-full items-center gap-4 rounded-xl text-left outline-none focus-visible:ring-2 focus-visible:ring-accent"
                      >
                        {/* Avatar / icon */}
                        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-border-default bg-surface-2 font-heading text-sm font-bold text-foreground-muted">
                          {team.name.charAt(0).toUpperCase()}
                        </div>
                        <div className="min-w-0">
                          <p className="font-semibold text-foreground">{team.name}</p>
                          <p className="mt-0.5 text-sm text-foreground-muted">
                            {team.member_count} {team.member_count === 1 ? "member" : "members"}
                          </p>
                        </div>
                        <ChevronDownIcon
                          className={`h-4 w-4 shrink-0 text-foreground-muted transition-transform ${
                            expandedTeamId === team.id ? "rotate-180" : ""
                          }`}
                        />
                      </button>
                      <TeamCapabilityToggles
                        isBusy={capabilityLoading}
                        onToggle={(capability, enabled) =>
                          openCapabilityConfirm(team, capability, enabled)
                        }
                        team={team}
                        orgCapabilities={capabilities}
                      />
                    </div>

                    {/* ── Actions ── */}
                    <div className="flex shrink-0 items-center gap-2">
                      <button
                        type="button"
                        onClick={() =>
                          setExpandedTeamId((prev) =>
                            prev === team.id ? null : team.id,
                          )
                        }
                        aria-expanded={expandedTeamId === team.id}
                        title="Add or remove members"
                        className="flex min-h-11 items-center gap-1.5 rounded-xl border border-accent/30 bg-accent/10 px-3 text-sm font-semibold text-accent transition-colors hover:bg-accent/20"
                      >
                        <PlusIcon className="h-4 w-4" />
                        <span className="hidden sm:inline">
                          {expandedTeamId === team.id ? "Close" : "Add members"}
                        </span>
                      </button>
                      <button
                        type="button"
                        disabled={isSuspended}
                        title="Rename team"
                        onClick={() => {
                          setEditingTeam(team);
                          setEditName(team.name);
                        }}
                        aria-label={`Rename ${team.name}`}
                        className="flex h-11 w-11 items-center justify-center rounded-xl border border-border-default bg-surface-1 text-foreground-muted transition-colors hover:border-border-strong hover:bg-surface-2 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        <Pencil1Icon className="h-4 w-4" />
                      </button>
                      <button
                        type="button"
                        disabled={isSuspended}
                        title="Delete team"
                        onClick={() => setTeamToDelete(team)}
                        aria-label={`Delete ${team.name}`}
                        className="flex h-11 w-11 items-center justify-center rounded-xl border border-error/30 bg-error/5 text-error transition-colors hover:bg-error/10 disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        <TrashIcon className="h-4 w-4" />
                      </button>
                    </div>
                  </>
                )}
               </div>

                {expandedTeamId === team.id && editingTeam?.id !== team.id && (
                  <TeamMemberManager
                    orgId={orgId}
                    teamId={team.id}
                    isAdmin={isAdmin}
                    isSuspended={isSuspended}
                    onChange={loadTeams}
                  />
                )}
              </li>
            ))}
          </ul>
        )}
      </div>

      <ConfirmDialog
        open={!!teamToDelete}
        title="Delete team?"
        description={`Are you sure you want to delete "${teamToDelete?.name}"? Members will be removed from the team but will remain in the organization.`}
        confirmLabel="Delete team"
        tone="danger"
        busy={deleteLoading}
        onConfirm={handleDelete}
        onClose={() => setTeamToDelete(null)}
      />
      <ConfirmDialog
        open={pendingCapabilityAction !== null}
        eyebrow="Capability"
        title={
          pendingCapabilityAction
            ? `${pendingCapabilityAction.enabled ? "Disable" : "Enable"} ${pendingCapabilityAction.capability[0].toUpperCase()}${pendingCapabilityAction.capability.slice(1)} on ${pendingCapabilityAction.teamName}?`
            : ""
        }
        description={
          pendingCapabilityAction ? (
            pendingCapabilityAction.enabled ? (
              <>Members of this team will lose this marketplace right.</>
            ) : (
              <>
                Every member of this team gains the{" "}
                {pendingCapabilityAction.capability} role.
              </>
            )
          ) : (
            ""
          )
        }
        confirmLabel={
          pendingCapabilityAction
            ? `${pendingCapabilityAction.enabled ? "Disable" : "Enable"} ${pendingCapabilityAction.capability[0].toUpperCase()}${pendingCapabilityAction.capability.slice(1)}`
            : "Confirm"
        }
        busy={capabilityLoading}
        error={capabilityError}
        onConfirm={handleConfirmCapabilityAction}
        onClose={closeCapabilityConfirm}
      />
    </div>
  );
}
