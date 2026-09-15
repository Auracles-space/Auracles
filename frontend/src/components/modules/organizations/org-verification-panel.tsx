"use client";

/**
 * Organization business-verification (KYB) panel.
 *
 * An organization establishes its legal identity here once, and every
 * capability reads that verdict: before verification it cannot activate
 * Contributor or Operator at all. Owner/admin only — plain members see the
 * status without the form. Saving legal identity is a sensitive action: the
 * API requires a step-up 2FA window, which the global step-up prompt handles
 * when the call is refused.
 *
 * Maps to: DESIGN-1.
 */
import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { StatusPill, ownerStatusKey } from "@/components/ui/status-pill";
import { useOrganization } from "@/components/modules/organizations/organization-context";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import {
  addOrgIncorporationDocument,
  getOrgKyb,
  removeOrgIncorporationDocument,
  submitOrgKyb,
  upsertLegalProfile,
} from "@/lib/generated/sdk.gen";
import type { OrgKybStatusResponse } from "@/lib/generated/types.gen";

/**
 * Country-specific wording for the registration number and its document.
 *
 * The platform is global but pilots in Nigeria, so the fields are one shape
 * everywhere and only the labels change. A reader who has a CAC certificate in
 * hand should not have to guess whether "registration number" means their RC
 * number.
 */
const REGISTRATION_LABELS: Record<string, { number: string; document: string }> =
  {
    NG: { number: "RC number", document: "Certificate of Incorporation (CAC)" },
    GB: { number: "Company number", document: "Certificate of Incorporation" },
    US: { number: "EIN or state registration number", document: "Formation document" },
  };

const GENERIC_LABELS = {
  number: "Business registration number",
  document: "Certificate of incorporation",
};

/** Human-readable file name from an incorporation-document S3 key. */
function documentName(key: string): string {
  const segment = key.split("/").pop() ?? key;
  // Keys are minted as `{uuid4}-{safe name}`; a uuid4 plus its hyphen is 37
  // characters, so anything after that is the name the uploader chose.
  return segment.length > 37 ? segment.slice(37) : segment;
}

/**
 * Render the organization's verification state and, for admins, its form.
 */
export function OrgVerificationPanel() {
  const { orgId, role } = useOrganization();
  const isAdmin = role === "owner" || role === "admin";

  const [kyb, setKyb] = useState<OrgKybStatusResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [legalName, setLegalName] = useState("");
  const [registrationNumber, setRegistrationNumber] = useState("");

  const load = useCallback(async () => {
    if (!orgId) return;
    configureBrowserClient();
    const result = await getOrgKyb({
      path: { org_id: orgId },
      headers: getAccessTokenHeaders(),
    });
    setLoading(false);
    if (!result.response.ok || !result.data) {
      setError(describeGeneratedError(result.error));
      return;
    }
    setKyb(result.data);
    setLegalName(result.data.legal_name ?? "");
    setRegistrationNumber(result.data.registration_number ?? "");
  }, [orgId]);

  useEffect(() => {
    void load();
  }, [load]);

  /**
   * Save the organization's legal identity.
   *
   * Step-up gated server-side: the legal name is what an admin verifies
   * against, so changing it is a sensitive write. The global step-up prompt
   * opens the window when the API refuses the call.
   */
  async function handleSaveIdentity() {
    if (!orgId) return;
    setBusy(true);
    setError(null);
    const result = await upsertLegalProfile({
      body: {
        legal_name: legalName.trim(),
        registration_number: registrationNumber.trim() || null,
      },
      path: { org_id: orgId },
      headers: getAccessTokenHeaders(),
    });
    setBusy(false);
    if (!result.response.ok) {
      setError(describeGeneratedError(result.error));
      return;
    }
    await load();
  }

  /** Upload one incorporation document straight to the private bucket. */
  async function handleUpload(file: File) {
    if (!orgId) return;
    setBusy(true);
    setError(null);
    const session = await addOrgIncorporationDocument({
      body: {
        content_type: file.type || "application/octet-stream",
        file_name: file.name,
        size_bytes: file.size,
      },
      path: { org_id: orgId },
      headers: getAccessTokenHeaders(),
    });
    if (!session.response.ok || !session.data) {
      setBusy(false);
      setError(describeGeneratedError(session.error));
      return;
    }
    const form = new FormData();
    Object.entries(session.data.fields).forEach(([name, value]) =>
      form.append(name, String(value)),
    );
    form.append("file", file);
    const upload = await fetch(session.data.url, { body: form, method: "POST" });
    setBusy(false);
    if (!upload.ok) {
      setError("The document could not be uploaded. Please try again.");
      return;
    }
    await load();
  }

  /** Detach one document before submission. */
  async function handleRemove(key: string) {
    if (!orgId) return;
    setBusy(true);
    setError(null);
    const result = await removeOrgIncorporationDocument({
      body: { s3_key: key },
      path: { org_id: orgId },
      headers: getAccessTokenHeaders(),
    });
    setBusy(false);
    if (!result.response.ok) {
      setError(describeGeneratedError(result.error));
      return;
    }
    await load();
  }

  /** Send the organization for review. */
  async function handleSubmit() {
    if (!orgId) return;
    setBusy(true);
    setError(null);
    const result = await submitOrgKyb({
      path: { org_id: orgId },
      headers: getAccessTokenHeaders(),
    });
    setBusy(false);
    if (!result.response.ok) {
      setError(describeGeneratedError(result.error));
      return;
    }
    await load();
  }

  if (loading) {
    return (
      <div className="flex min-h-64 items-center justify-center">
        <Spinner className="h-8 w-8 text-accent" />
      </div>
    );
  }

  const status = kyb?.kyb_status ?? "unverified";
  const labels = REGISTRATION_LABELS[kyb?.country ?? ""] ?? GENERIC_LABELS;
  const documents = kyb?.incorporation_doc_keys ?? [];
  const locked = status === "verified" || status === "pending";
  // Saving identical details would still cost a step-up prompt and an audit
  // row, so the save only enables once the trimmed fields differ.
  const identityChanged =
    legalName.trim() !== (kyb?.legal_name ?? "") ||
    registrationNumber.trim() !== (kyb?.registration_number ?? "");
  const canSubmit =
    isAdmin &&
    !busy &&
    !locked &&
    Boolean(kyb?.legal_name) &&
    Boolean(kyb?.registration_number) &&
    documents.length > 0;

  return (
    <section className="grid gap-6">
      <div className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
              Business verification
            </p>
            <h1 className="mt-2 font-heading text-2xl font-bold text-foreground">
              Verify this organization
            </h1>
          </div>
          <StatusPill status={ownerStatusKey(status, "kyb")} />
        </div>
        <p className="mt-3 max-w-2xl text-sm leading-6 text-foreground-muted">
          {status === "verified"
            ? "This organization is verified. Its legal details are fixed to what was reviewed; contact support if they need to change."
            : "An organization is verified before it can act on Auracles. Until then it cannot activate the Contributor or Operator capability, publish, or transact."}
        </p>
        {status === "rejected" && kyb?.kyb_review_notes ? (
          <p className="mt-4 rounded-xl border border-error/30 bg-error/10 p-4 text-sm text-error">
            {kyb.kyb_review_notes}
          </p>
        ) : null}
        {status === "pending" ? (
          <p className="mt-4 rounded-xl border border-border-default bg-surface-2 p-4 text-sm text-foreground-muted">
            In review. We will notify you as soon as an administrator has
            decided; nothing else is needed from you right now.
          </p>
        ) : null}
      </div>

      {error ? (
        <p className="rounded-xl border border-error/30 bg-error/10 p-4 text-sm text-error">
          {error}
        </p>
      ) : null}

      <div className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
        <h2 className="font-heading text-lg font-bold text-foreground">
          Legal identity
        </h2>
        <div className="mt-4 grid gap-4 md:grid-cols-2">
          <label className="grid gap-2 text-sm font-semibold text-foreground">
            Registered legal name
            <Input
              disabled={!isAdmin || locked || busy}
              onChange={(event) => setLegalName(event.target.value)}
              placeholder="Acme Attestations Ltd"
              value={legalName}
            />
          </label>
          <label className="grid gap-2 text-sm font-semibold text-foreground">
            {labels.number}
            <Input
              disabled={!isAdmin || locked || busy}
              onChange={(event) => setRegistrationNumber(event.target.value)}
              placeholder="RC123456"
              value={registrationNumber}
            />
          </label>
        </div>
        {isAdmin && !locked ? (
          <div className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-end">
            <span className="text-xs leading-5 text-foreground-muted">
              Saving legal details requires two-factor authentication.{" "}
              <a
                className="font-medium text-accent hover:underline"
                href="/2fa-setup"
              >
                Set it up first
              </a>{" "}
              if you have not already.
            </span>
            <Button
              disabled={busy || !identityChanged || legalName.trim().length < 2}
              loading={busy}
              onClick={handleSaveIdentity}
            >
              Save legal identity
            </Button>
          </div>
        ) : null}
      </div>

      <div className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
        <h2 className="font-heading text-lg font-bold text-foreground">
          {labels.document}
        </h2>
        <p className="mt-1 text-sm leading-6 text-foreground-muted">
          Upload the document that proves this registration. It is stored
          privately and is only ever opened by a reviewing administrator.
        </p>
        {documents.length > 0 ? (
          <ul className="mt-4 grid gap-2">
            {documents.map((key) => (
              <li
                className="flex min-h-12 flex-wrap items-center justify-between gap-3 rounded-xl border border-border-default bg-surface-2 px-4 py-2 text-sm text-foreground"
                key={key}
              >
                <span className="break-all">{documentName(key)}</span>
                {isAdmin && !locked ? (
                  <button
                    className="min-h-11 rounded-xl border border-error/50 px-4 text-sm font-semibold text-error outline-none transition-colors hover:bg-error/10 focus-visible:ring-2 focus-visible:ring-error disabled:cursor-not-allowed disabled:opacity-60"
                    disabled={busy}
                    onClick={() => handleRemove(key)}
                    type="button"
                  >
                    Remove
                  </button>
                ) : null}
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-4 rounded-xl border border-border-default bg-surface-2 p-4 text-sm text-foreground-muted">
            No document attached yet.
          </p>
        )}
        {isAdmin && !locked ? (
          <label className="mt-4 grid gap-2 text-sm font-semibold text-foreground">
            <span>Add a document</span>
            <input
              accept="application/pdf,image/png,image/jpeg"
              className="min-h-12 rounded-xl border border-border-default bg-background px-4 py-2 text-sm text-foreground outline-none file:mr-4 file:rounded-lg file:border-0 file:bg-surface-2 file:px-4 file:py-2 file:text-sm file:font-semibold file:text-foreground focus-visible:ring-2 focus-visible:ring-accent"
              disabled={busy}
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) void handleUpload(file);
                event.target.value = "";
              }}
              type="file"
            />
          </label>
        ) : null}
      </div>

      {isAdmin && !locked ? (
        <div className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
          <Button disabled={!canSubmit} loading={busy} onClick={handleSubmit}>
            Submit for verification
          </Button>
          {!canSubmit ? (
            <p className="mt-3 text-sm text-foreground-muted">
              Add the legal name, {labels.number.toLowerCase()}, and at least one
              document before submitting.
            </p>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
