"use client";

import { useEffect, useState } from "react";
import { 
  listTeamsV1OrgsOrgIdTeamsGet,
  createTeamV1OrgsOrgIdTeamsPost,
  renameTeamV1OrgsOrgIdTeamsTeamIdPatch,
  deleteTeamV1OrgsOrgIdTeamsTeamIdDelete
} from "@/lib/generated/sdk.gen";
import type { OrgTeamResponse } from "@/lib/generated/types.gen";
import { getAccessTokenHeaders } from "@/lib/auth/form-client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { useOrganization } from "./organization-context";
import { Pencil1Icon } from "@radix-ui/react-icons";

export function OrganizationTeams() {
  const { orgId, role, isSuspended } = useOrganization();
  const isAdmin = role === "admin" || role === "owner";

  const [teams, setTeams] = useState<OrgTeamResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Create State
  const [newTeamName, setNewTeamName] = useState("");
  const [createLoading, setCreateLoading] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  // Edit State
  const [editingTeam, setEditingTeam] = useState<OrgTeamResponse | null>(null);
  const [editName, setEditName] = useState("");
  const [editLoading, setEditLoading] = useState(false);
  const [editError, setEditError] = useState<string | null>(null);

  // Delete State
  const [teamToDelete, setTeamToDelete] = useState<OrgTeamResponse | null>(null);
  const [deleteLoading, setDeleteLoading] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

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
        setError("Failed to load teams.");
      }
    } catch (err) {
      setError("An error occurred loading teams.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadTeams();
  }, [orgId, isAdmin]);

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
        setCreateError(result.error?.detail?.error_code || "Failed to create team");
      } else {
        setNewTeamName("");
        await loadTeams();
      }
    } catch (err) {
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
        setEditError(result.error?.detail?.error_code || "Failed to rename team");
        setEditLoading(false);
      } else {
        setEditingTeam(null);
        setEditLoading(false);
        await loadTeams();
      }
    } catch (err) {
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
        setDeleteError(result.error?.detail?.error_code || "Failed to delete team");
        setDeleteLoading(false);
        setTeamToDelete(null);
      } else {
        setTeamToDelete(null);
        setDeleteLoading(false);
        await loadTeams();
      }
    } catch (err) {
      setDeleteError("Unexpected error occurred while deleting team.");
      setDeleteLoading(false);
      setTeamToDelete(null);
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
    <div className="flex flex-col gap-8 max-w-4xl">
      {/* Create Form */}
      <div className="rounded-2xl border border-border-default bg-surface-1 shadow-sm p-6">
        <h2 className="mb-4 font-heading text-xl font-bold text-foreground">
          Create Team
        </h2>
        {createError && (
          <div className="mb-4 rounded-xl border border-error/50 bg-error/5 p-4 text-sm text-error">
            {createError}
          </div>
        )}
        <form onSubmit={handleCreate} className="flex flex-col sm:flex-row gap-4 items-end">
          <div className="flex-grow w-full">
            <label htmlFor="teamName" className="mb-1 block text-sm font-semibold text-foreground">
              Team Name
            </label>
            <Input
              id="teamName"
              required
              disabled={isSuspended}
              value={newTeamName}
              onChange={(e) => setNewTeamName(e.target.value)}
              placeholder="e.g. Engineering"
            />
          </div>
          <Button type="submit" loading={createLoading} disabled={isSuspended || !newTeamName} className="w-full sm:w-auto mt-4 sm:mt-0">
            Create Team
          </Button>
        </form>
      </div>

      {/* Teams List */}
      <div className="rounded-2xl border border-border-default bg-surface-1 shadow-sm">
        <div className="border-b border-border-default p-6">
          <h2 className="font-heading text-xl font-bold text-foreground">
            Teams
          </h2>
          <p className="mt-1 text-sm text-foreground-muted">
            Manage your organization's teams.
          </p>
        </div>

        {error && (
          <div className="m-6 mb-0 rounded-xl border border-error/50 bg-error/5 p-4 text-sm text-error">
            {error}
          </div>
        )}
        {editError && (
          <div className="m-6 mb-0 rounded-xl border border-error/50 bg-error/5 p-4 text-sm text-error">
            {editError}
          </div>
        )}
        {deleteError && (
          <div className="m-6 mb-0 rounded-xl border border-error/50 bg-error/5 p-4 text-sm text-error">
            {deleteError}
          </div>
        )}

        <ul className="divide-y divide-border-default">
          {teams.length === 0 ? (
            <li className="p-6 text-center text-foreground-muted">No teams created yet.</li>
          ) : (
            teams.map((team) => (
              <li key={team.id} className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 p-6 hover:bg-surface-2 transition-colors">
                {editingTeam?.id === team.id ? (
                  <form onSubmit={handleEditSubmit} className="flex flex-1 items-center gap-3">
                    <Input
                      autoFocus
                      disabled={editLoading || isSuspended}
                      value={editName}
                      onChange={(e) => setEditName(e.target.value)}
                      className="max-w-xs"
                    />
                    <Button type="submit" loading={editLoading} disabled={isSuspended || !editName.trim()}>Save</Button>
                    <Button type="button" variant="secondary" onClick={() => setEditingTeam(null)}>Cancel</Button>
                  </form>
                ) : (
                  <>
                    <div>
                      <p className="font-semibold text-foreground flex items-center gap-2">
                        {team.name}
                        <button 
                          type="button" 
                          disabled={isSuspended}
                          onClick={() => {
                            setEditingTeam(team);
                            setEditName(team.name);
                          }}
                          className="text-foreground-muted hover:text-foreground p-1 rounded transition-colors disabled:opacity-50"
                        >
                          <Pencil1Icon className="h-4 w-4" />
                        </button>
                      </p>
                      <p className="mt-1 text-sm text-foreground-muted">
                        {team.member_count} {team.member_count === 1 ? "member" : "members"}
                      </p>
                    </div>

                    <div className="flex items-center gap-3 shrink-0">
                      <Button
                        variant="destructive"
                        className="min-h-10 px-4 py-1"
                        disabled={isSuspended}
                        onClick={() => setTeamToDelete(team)}
                      >
                        Delete
                      </Button>
                    </div>
                  </>
                )}
              </li>
            ))
          )}
        </ul>
      </div>

      <ConfirmDialog
        open={!!teamToDelete}
        title={`Delete Team?`}
        description={`Are you sure you want to delete the team "${teamToDelete?.name}"? Members will be removed from the team, but they will remain in the organization.`}
        confirmLabel="Delete Team"
        tone="danger"
        busy={deleteLoading}
        onConfirm={handleDelete}
        onClose={() => setTeamToDelete(null)}
      />
    </div>
  );
}
