"use client";

/**
 * Credential management UI for Attestation targets.
 *
 * Credentials are user-owned records that can later be submitted for formal
 * Attestation. Evidence uploads are handled by the backend upload-session API;
 * this MVP panel manages the durable credential records first.
 */
import { useEffect, useState } from "react";

import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import {
  createCredential,
  deleteCredential,
  listCredentials,
} from "@/lib/generated/sdk.gen";
import type { CredentialResponse } from "@/lib/generated/types.gen";

/**
 * Render user-owned Credentials and a create form.
 */
export function CredentialManager() {
  const [credentials, setCredentials] = useState<CredentialResponse[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [expiresDate, setExpiresDate] = useState("");
  const [issuedDate, setIssuedDate] = useState("");
  const [issuer, setIssuer] = useState("");
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [title, setTitle] = useState("");

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
   */
  async function handleCreateCredential() {
    setError(null);
    setSubmitting(true);
    configureBrowserClient();
    const result = await createCredential({
      body: {
        expires_date: expiresDate || null,
        issued_date: issuedDate,
        issuer,
        title,
      },
      headers: getAccessTokenHeaders(),
    });
    setSubmitting(false);

    if (!result.response.ok || !result.data) {
      setError(describeGeneratedError(result.error));
      return;
    }

    setCredentials((current) => [result.data, ...current]);
    setExpiresDate("");
    setIssuedDate("");
    setIssuer("");
    setTitle("");
  }

  /**
   * Delete one Credential owned by the current user.
   *
   * @param credentialId - Credential UUID to remove.
   */
  async function handleDeleteCredential(credentialId: string) {
    setError(null);
    configureBrowserClient();
    const result = await deleteCredential({
      headers: getAccessTokenHeaders(),
      path: { credential_id: credentialId },
    });
    if (!result.response.ok) {
      setError(describeGeneratedError(result.error));
      return;
    }
    setCredentials((current) =>
      current.filter((credential) => credential.id !== credentialId),
    );
  }

  if (loading) {
    return <p className="text-sm text-foreground-muted">Loading credentials.</p>;
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
        {error ? <p className="mt-4 rounded-xl border border-error/30 bg-error/10 p-4 text-sm text-error">{error}</p> : null}
      </div>

      <div className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
        <h2 className="font-heading text-xl font-bold text-foreground">
          Add credential
        </h2>
        <div className="mt-4 grid gap-4 md:grid-cols-2">
          <label className="grid gap-2 text-sm font-semibold text-foreground">
            Credential title
            <input
              className="min-h-11 rounded-xl border border-border-default bg-background px-3 text-sm font-medium text-foreground outline-none transition-all focus-visible:ring-2 focus-visible:ring-accent"
              onChange={(event) => setTitle(event.target.value)}
              value={title}
            />
          </label>
          <label className="grid gap-2 text-sm font-semibold text-foreground">
            Issuer
            <input
              className="min-h-11 rounded-xl border border-border-default bg-background px-3 text-sm font-medium text-foreground outline-none transition-all focus-visible:ring-2 focus-visible:ring-accent"
              onChange={(event) => setIssuer(event.target.value)}
              value={issuer}
            />
          </label>
          <label className="grid gap-2 text-sm font-semibold text-foreground">
            Issued date
            <input
              className="min-h-11 rounded-xl border border-border-default bg-background px-3 text-sm font-medium text-foreground outline-none transition-all focus-visible:ring-2 focus-visible:ring-accent"
              onChange={(event) => setIssuedDate(event.target.value)}
              type="date"
              value={issuedDate}
            />
          </label>
          <label className="grid gap-2 text-sm font-semibold text-foreground">
            Expiry date
            <input
              className="min-h-11 rounded-xl border border-border-default bg-background px-3 text-sm font-medium text-foreground outline-none transition-all focus-visible:ring-2 focus-visible:ring-accent"
              onChange={(event) => setExpiresDate(event.target.value)}
              type="date"
              value={expiresDate}
            />
          </label>
        </div>
        <button
          className="mt-5 min-h-11 rounded-xl bg-foreground px-4 text-sm font-semibold text-background shadow-sm outline-none transition hover:bg-foreground/90 focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-60"
          disabled={!title || !issuer || !issuedDate || submitting}
          onClick={handleCreateCredential}
          type="button"
        >
          {submitting ? "Adding credential" : "Add credential"}
        </button>
      </div>

      <div className="grid gap-3">
        {credentials.length === 0 ? (
          <p className="rounded-2xl border border-border-default bg-surface-1 p-6 text-sm text-foreground-muted">
            No credentials have been added yet.
          </p>
        ) : (
          credentials.map((credential) => (
            <article
              className="grid gap-4 rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm md:grid-cols-[minmax(0,1fr)_auto] md:items-center"
              key={credential.id}
            >
              <div>
                <h3 className="font-heading text-lg font-bold text-foreground">
                  {credential.title}
                </h3>
                <p className="mt-1 text-sm text-foreground-muted">
                  {credential.issuer} · issued {credential.issued_date}
                  {credential.expires_date
                    ? ` · expires ${credential.expires_date}`
                    : ""}
                </p>
                <p className="mt-2 text-xs font-semibold uppercase tracking-[0.05em] text-foreground-muted">
                  {credential.evidence_file_keys.length} evidence files
                </p>
              </div>
              <button
                className="min-h-11 rounded-xl border border-error px-4 text-sm font-semibold text-error outline-none transition hover:bg-error/10 focus-visible:ring-2 focus-visible:ring-error"
                onClick={() => handleDeleteCredential(credential.id)}
                type="button"
              >
                Delete
              </button>
            </article>
          ))
        )}
      </div>
    </section>
  );
}
