"use client";

/**
 * Credential management UI for Attestation targets.
 *
 * Credentials are user-owned records that move through a verification lifecycle
 * (unverified → pending → verified | rejected). This container loads the owner's
 * credentials, hosts the create/edit form, and wires the lifecycle actions
 * (edit, delete, submit-for-verification) to the generated SDK. Evidence files
 * are uploaded from the edit form and persisted via evidence_file_keys on save;
 * a 409 on update means the new evidence is still being scanned.
 *
 * Maps to: FR-ATT credential verification lifecycle.
 */
import { useEffect, useState } from "react";

import { CredentialCard } from "./credential-card";
import { CredentialForm, type CredentialFormValues } from "./credential-form";

import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import { TableSkeleton } from "@/components/ui/skeletons/table-skeleton";
import {
  createCredential,
  deleteCredential,
  listCredentials,
  submitCredentialV1CredentialsCredentialIdSubmitPost,
  updateCredentialV1CredentialsCredentialIdPatch,
} from "@/lib/generated/sdk.gen";
import type { CredentialResponse } from "@/lib/generated/types.gen";

/**
 * Render user-owned Credentials, the create/edit form, and lifecycle actions.
 */
export function CredentialManager() {
  const [credentials, setCredentials] = useState<CredentialResponse[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [editing, setEditing] = useState<CredentialResponse | null>(null);

  useEffect(() => {
    async function loadCredentials() {
      configureBrowserClient();
      const result = await listCredentials({ headers: getAccessTokenHeaders() });
      if (!result.response.ok || !result.data) {
        setError(describeGeneratedError(result.error));
        setLoading(false);
        return;
      }
      setCredentials(result.data.credentials);
      setLoading(false);
    }

    void loadCredentials();
  }, []);

  /**
 * Persist a new user-owned Credential through the generated SDK.
 *
 * @param values - Normalised form values from the create form.
 */
  async function handleCreateCredential(values: CredentialFormValues) {
    setError(null);
    setSubmitting(true);
    configureBrowserClient();
    const result = await createCredential({
      body: values,
      headers: getAccessTokenHeaders(),
    });
    setSubmitting(false);

    if (!result.response.ok || !result.data) {
      setError(describeGeneratedError(result.error));
      return;
    }

    setCredentials((current) => [result.data, ...current]);
    setEditing(result.data);
  }

  /**
   * Update the credential currently in edit mode through the generated SDK.
   *
   * @param values - Normalised form values from the edit form.
   */
  async function handleUpdateCredential(values: CredentialFormValues) {
    if (!editing) {
      return;
    }
    setError(null);
    setSubmitting(true);
    configureBrowserClient();
    const result = await updateCredentialV1CredentialsCredentialIdPatch({
      body: values,
      headers: getAccessTokenHeaders(),
      path: { credential_id: editing.id },
    });
    setSubmitting(false);

    if (!result.response.ok || !result.data) {
      // A 409 means freshly uploaded evidence is still being virus-scanned;
      // the save is safe to retry once scanning settles.
      if (result.response.status === 409) {
        setError(
          "Evidence is still being scanned — try saving again in a moment.",
        );
        return;
      }
      setError(describeGeneratedError(result.error));
      return;
    }

    const updated = result.data;
    setCredentials((current) =>
      current.map((credential) =>
        credential.id === updated.id ? updated : credential,
      ),
    );
    setEditing(null);
  }

  /**
   * Submit one Credential for verification review.
   *
   * @param credentialId - Credential UUID to submit.
   */
  async function handleSubmitForVerification(credentialId: string) {
    setError(null);
    setBusyId(credentialId);
    configureBrowserClient();
    const result = await submitCredentialV1CredentialsCredentialIdSubmitPost({
      headers: getAccessTokenHeaders(),
      path: { credential_id: credentialId },
    });
    setBusyId(null);

    if (!result.response.ok || !result.data) {
      setError(describeGeneratedError(result.error));
      return;
    }

    const updated = result.data;
    setCredentials((current) =>
      current.map((credential) =>
        credential.id === updated.id ? updated : credential,
      ),
    );
  }

  /**
   * Delete one Credential owned by the current user.
   *
   * @param credentialId - Credential UUID to remove.
   */
  async function handleDeleteCredential(credentialId: string) {
    setError(null);
    setBusyId(credentialId);
    configureBrowserClient();
    const result = await deleteCredential({
      headers: getAccessTokenHeaders(),
      path: { credential_id: credentialId },
    });
    setBusyId(null);
    if (!result.response.ok) {
      setError(describeGeneratedError(result.error));
      return;
    }
    if (editing?.id === credentialId) {
      setEditing(null);
    }
    setCredentials((current) =>
      current.filter((credential) => credential.id !== credentialId),
    );
  }

  if (loading) {
    return <TableSkeleton />;
  }

  return (
    <section className="grid gap-6">
      <div className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
        <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
          Credentials
        </p>
        <h1 className="mt-2 font-heading text-3xl font-bold text-foreground">
          Professional credentials
        </h1>
        <p className="mt-2 max-w-2xl text-sm leading-6 text-foreground-muted">
          Add credentials that can be independently attested and displayed as
          public trust signals.
        </p>
        {error ? (
          <p className="mt-4 rounded-xl border border-error/30 bg-error/10 p-4 text-sm text-error">
            {error}
          </p>
        ) : null}
      </div>

      <div className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
        {editing ? (
          <>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="grid gap-1">
                <h2 className="font-heading text-xl font-bold text-foreground">
                  Edit credential
                </h2>
                <p className="text-sm text-foreground-muted">
                  Upload supporting PDF, Word, or image evidence before you
                  submit this credential for verification.
                </p>
              </div>
              <div className="flex items-center gap-3">
                <p className="rounded-xl border border-success/30 bg-success/10 px-3 py-2 text-xs font-semibold text-success">
                  Credential saved. You can add evidence now.
                </p>
                <button
                  className="min-h-12 rounded-xl border border-border-default bg-surface-1 px-6 text-sm font-semibold text-foreground outline-none transition-colors hover:bg-surface-2 focus-visible:ring-2 focus-visible:ring-accent"
                  onClick={() => setEditing(null)}
                  type="button"
                >
                  Cancel
                </button>
              </div>
            </div>
            <div className="mt-4">
              <CredentialForm
                initial={editing}
                key={editing.id}
                mode="edit"
                onSubmit={handleUpdateCredential}
                submitting={submitting}
              />
            </div>
          </>
        ) : (
          <>
            <h2 className="font-heading text-xl font-bold text-foreground">
              Add credential
            </h2>
            <div className="mt-4">
              <CredentialForm
                mode="create"
                onSubmit={handleCreateCredential}
                submitting={submitting}
              />
            </div>
          </>
        )}
      </div>

      <div className="grid gap-3">
        {credentials.length === 0 ? (
          <p className="rounded-2xl border border-border-default bg-surface-1 p-6 text-sm text-foreground-muted">
            No credentials have been added yet.
          </p>
        ) : (
          credentials.map((credential) => (
            <CredentialCard
              busy={busyId === credential.id}
              credential={credential}
              key={credential.id}
              onDelete={handleDeleteCredential}
              onEdit={setEditing}
              onSubmitForVerification={handleSubmitForVerification}
            />
          ))
        )}
      </div>
    </section>
  );
}
