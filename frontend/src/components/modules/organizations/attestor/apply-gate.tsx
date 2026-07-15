"use client";

import { useState } from "react";
import {
  addAttestorIncorporationDocumentV1OrgsOrgIdAttestorApplicationIncorporationDocumentPost as addIncorporationDocument,
  createOrgAttestorApplication,
  removeAttestorIncorporationDocumentV1OrgsOrgIdAttestorApplicationIncorporationDocumentDelete as removeIncorporationDocument,
  submitOrgAttestorApplication,
  updateOrgAttestorApplication,
} from "@/lib/generated/sdk.gen";
import type { OrgAttestorApplicationResponse } from "@/lib/generated/types.gen";
import { describeGeneratedError, getAccessTokenHeaders } from "@/lib/auth/form-client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { isLengthBetween, isNonEmpty } from "@/lib/forms/validators";
import {
  FUNCTION_OPTIONS,
  JURISDICTION_OPTIONS,
  SECTOR_OPTIONS,
} from "@/lib/marketplace/taxonomy";

/** Red asterisk marking a field the backend requires (NOT NULL). */
function RequiredMark() {
  return (
    <span aria-hidden="true" className="ml-0.5 text-error">
      *
    </span>
  );
}

/**
 * Derive a human-readable file name from an incorporation-document S3 key.
 *
 * Keys are stored as `.../{uuid}-{original-file-name}`, so strip the path and
 * the generated UUID prefix to show the name the uploader recognizes.
 *
 * @param key - The stored S3 object key.
 * @returns The original file name, or the last path segment as a fallback.
 */
function docLabel(key: string): string {
  const segment = key.split("/").pop() ?? key;
  const uuidPrefix =
    /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}-/i;
  return segment.replace(uuidPrefix, "");
}

export function ApplyGate({
  orgId,
  application,
  onChange,
}: {
  orgId: string;
  application: OrgAttestorApplicationResponse | null;
  onChange: () => void;
}) {
  const isDraft = !application || application.status === "draft";
  const isNeedsInfo = application?.status === "needs_info";
  const canEdit = isDraft || isNeedsInfo;

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [docFile, setDocFile] = useState<File | null>(null);

  const [formData, setFormData] = useState({
    legal_name: application?.legal_name || "",
    registration_number: application?.registration_number || "",
    credentials_summary: application?.credentials_summary || "",
    professional_references: application?.professional_references || "",
    sample_work_url: (application?.sample_work as { url: string })?.url || "",
    sectors: application?.sectors || [],
    functions: application?.functions || [],
    jurisdictions: application?.jurisdictions || [],
  });

  // Incorporation docs are server-owned (attached via the dedicated endpoint),
  // so read them from the live application, not editable form state.
  const incorporationDocs = application?.incorporation_doc_keys ?? [];
  const isNew = !application;

  // Submit runs the backend `_kyb_complete` check: legal_name, registration
  // number, at least one incorporation document, credentials, references, and
  // all three taxonomy lists (sample_work stays optional).
  const isComplete =
    isLengthBetween(formData.legal_name, 2, 200) &&
    isNonEmpty(formData.registration_number) &&
    incorporationDocs.length > 0 &&
    isLengthBetween(formData.credentials_summary, 10, 5000) &&
    isLengthBetween(formData.professional_references, 3, 5000) &&
    formData.sectors.length > 0 &&
    formData.functions.length > 0 &&
    formData.jurisdictions.length > 0;

  // Creating the draft row only needs the columns the create endpoint marks
  // required; legal_name, registration_number, and docs are attached afterward.
  const canCreate =
    isLengthBetween(formData.credentials_summary, 10, 5000) &&
    isLengthBetween(formData.professional_references, 3, 5000) &&
    formData.sectors.length > 0 &&
    formData.functions.length > 0 &&
    formData.jurisdictions.length > 0;

  const saveDraftDisabled = loading || (isNew && !canCreate);
  const submitDisabled = loading || !isComplete;

  type ListField = "sectors" | "functions" | "jurisdictions";

  /** Append a selected taxonomy value to a list field, ignoring duplicates. */
  function addValue(field: ListField, value: string) {
    if (!value) return;
    setFormData((prev) =>
      prev[field].includes(value)
        ? prev
        : { ...prev, [field]: [...prev[field], value] },
    );
  }

  /** Remove a value from a list field. */
  function removeValue(field: ListField, value: string) {
    setFormData((prev) => ({
      ...prev,
      [field]: prev[field].filter((v) => v !== value),
    }));
  }

  async function handleSaveDraft() {
    setLoading(true);
    setError(null);
    try {
      const body = {
        legal_name: formData.legal_name,
        registration_number: formData.registration_number,
        credentials_summary: formData.credentials_summary,
        professional_references: formData.professional_references,
        sample_work: { url: formData.sample_work_url },
        sectors: formData.sectors,
        functions: formData.functions,
        jurisdictions: formData.jurisdictions,
      };
      let res;
      if (!application) {
        res = await createOrgAttestorApplication({
          path: { org_id: orgId },
          body,
          headers: getAccessTokenHeaders(),
        });
      } else {
        res = await updateOrgAttestorApplication({
          path: { org_id: orgId },
          body,
          headers: getAccessTokenHeaders(),
        });
      }
      if (res.error) {
        setError(describeGeneratedError(res.error));
      } else {
        onChange();
      }
    } catch {
      setError("An unexpected error occurred.");
    } finally {
      setLoading(false);
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      // First save draft
      const body = {
        legal_name: formData.legal_name,
        registration_number: formData.registration_number,
        credentials_summary: formData.credentials_summary,
        professional_references: formData.professional_references,
        sample_work: { url: formData.sample_work_url },
        sectors: formData.sectors,
        functions: formData.functions,
        jurisdictions: formData.jurisdictions,
      };

      let updateRes;
      if (!application) {
        updateRes = await createOrgAttestorApplication({
          path: { org_id: orgId },
          body,
          headers: getAccessTokenHeaders(),
        });
      } else {
        updateRes = await updateOrgAttestorApplication({
          path: { org_id: orgId },
          body,
          headers: getAccessTokenHeaders(),
        });
      }

      if (updateRes.error) {
        setError(describeGeneratedError(updateRes.error));
        setLoading(false);
        return;
      }

      const res = await submitOrgAttestorApplication({
        path: { org_id: orgId },
        headers: getAccessTokenHeaders(),
      });
      if (res.error) {
        setError(describeGeneratedError(res.error));
      } else {
        onChange();
      }
    } catch {
      setError("An unexpected error occurred.");
    } finally {
      setLoading(false);
    }
  }

  /** Attach the selected incorporation document to the application. */
  async function handleAddDoc() {
    if (!docFile) return;
    setLoading(true);
    setError(null);
    try {
      const res = await addIncorporationDocument({
        path: { org_id: orgId },
        body: {
          file_name: docFile.name,
          content_type: docFile.type || "application/octet-stream",
          size_bytes: docFile.size,
        },
        headers: getAccessTokenHeaders(),
      });
      if (res.error || !res.data) {
        setError(describeGeneratedError(res.error));
        return;
      }

      // The session only reserves the S3 key; the file must still be pushed to
      // the bucket, or the admin download later resolves to a missing object.
      const form = new FormData();
      for (const [key, value] of Object.entries(res.data.fields)) {
        form.append(key, String(value));
      }
      form.append("file", docFile);
      const upload = await fetch(res.data.url, { method: "POST", body: form });
      if (!upload.ok) {
        setError("The upload could not be completed. Try again.");
        return;
      }

      setDocFile(null);
      onChange();
    } catch {
      setError("An unexpected error occurred.");
    } finally {
      setLoading(false);
    }
  }

  /**
   * Detach one incorporation document from the application.
   *
   * @param key - S3 key of the document to remove.
   */
  async function handleRemoveDoc(key: string) {
    setLoading(true);
    setError(null);
    try {
      const res = await removeIncorporationDocument({
        path: { org_id: orgId },
        body: { s3_key: key },
        headers: getAccessTokenHeaders(),
      });
      if (res.error) {
        setError(describeGeneratedError(res.error));
      } else {
        onChange();
      }
    } catch {
      setError("An unexpected error occurred.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="rounded-xl border border-border-default bg-surface-1 p-5 shadow-sm">
      {error && (
        <div className="mb-6 rounded-lg border border-error/50 bg-error/5 p-4 text-sm text-error">
          {error}
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label htmlFor="legal_name" className="mb-1 block text-sm font-semibold text-foreground">
            Legal Name
            <RequiredMark />
          </label>
          <Input
            id="legal_name"
            disabled={!canEdit}
            value={formData.legal_name}
            onChange={(e) => setFormData({ ...formData, legal_name: e.target.value })}
            placeholder="Audit Ltd."
          />
        </div>

        <div>
          <label
            htmlFor="registration_number"
            className="mb-1 block text-sm font-semibold text-foreground"
          >
            Registration Number
            <RequiredMark />
          </label>
          <Input
            id="registration_number"
            disabled={!canEdit}
            value={formData.registration_number}
            onChange={(e) =>
              setFormData({ ...formData, registration_number: e.target.value })
            }
            placeholder="RC123456"
          />
        </div>

        <div>
          <label
            htmlFor="credentials_summary"
            className="mb-1 block text-sm font-semibold text-foreground"
          >
            Credentials Summary
            <RequiredMark />
          </label>
          <Textarea
            id="credentials_summary"
            disabled={!canEdit}
            value={formData.credentials_summary}
            onChange={(e) => setFormData({ ...formData, credentials_summary: e.target.value })}
            placeholder="Summary of relevant experience..."
          />
        </div>

        <div>
          <label htmlFor="sample_work" className="mb-1 block text-sm font-semibold text-foreground">
            Sample Work (URL)
          </label>
          <Input
            id="sample_work"
            disabled={!canEdit}
            value={formData.sample_work_url}
            onChange={(e) => setFormData({ ...formData, sample_work_url: e.target.value })}
            placeholder="https://..."
          />
        </div>

        <div>
          <label htmlFor="references" className="mb-1 block text-sm font-semibold text-foreground">
            Professional References
            <RequiredMark />
          </label>
          <Textarea
            id="references"
            disabled={!canEdit}
            value={formData.professional_references}
            onChange={(e) => setFormData({ ...formData, professional_references: e.target.value })}
            placeholder="Names and contact info of references..."
          />
        </div>

        <div>
          <label className="mb-1 block text-sm font-semibold text-foreground">
            Incorporation Documents
            <RequiredMark />
          </label>
          <p className="mb-2 text-xs text-foreground-muted">
            Attach your certificate of incorporation and related KYB evidence.
          </p>

          {incorporationDocs.length > 0 && (
            <ul className="mb-3 grid gap-2">
              {incorporationDocs.map((key) => (
                <li
                  key={key}
                  className="flex items-center justify-between gap-3 rounded-lg border border-border-default bg-surface-2 px-3 py-2 text-sm text-foreground"
                >
                  <span className="truncate">{docLabel(key)}</span>
                  {canEdit && (
                    <button
                      type="button"
                      onClick={() => handleRemoveDoc(key)}
                      disabled={loading}
                      className="min-h-11 shrink-0 cursor-pointer text-xs font-semibold text-error hover:underline disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      Remove
                    </button>
                  )}
                </li>
              ))}
            </ul>
          )}

          {isNew ? (
            <p className="text-xs text-foreground-muted">
              Save a draft first to attach incorporation documents.
            </p>
          ) : (
            canEdit && (
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
                <div className="flex flex-1 items-center gap-3 rounded-xl border border-border-default bg-background px-3 py-2">
                  <label
                    htmlFor="incorporation_document_file"
                    className="inline-flex min-h-11 shrink-0 cursor-pointer items-center rounded-lg bg-foreground px-4 text-sm font-semibold text-background transition-colors hover:bg-foreground/90"
                  >
                    Choose file
                  </label>
                  <span className="truncate text-sm text-foreground-muted">
                    {docFile ? docFile.name : "No file selected"}
                  </span>
                  <input
                    id="incorporation_document_file"
                    aria-label="Incorporation document file"
                    type="file"
                    accept=".pdf,image/*"
                    onChange={(e) => setDocFile(e.target.files?.[0] || null)}
                    className="sr-only"
                  />
                </div>
                <Button
                  type="button"
                  variant="secondary"
                  onClick={handleAddDoc}
                  disabled={loading || !docFile}
                >
                  Add document
                </Button>
              </div>
            )
          )}
        </div>

        <MultiAddSelect
          label="Sectors"
          required
          placeholder="Add a sector"
          hint="Select at least one sector your organization can attest."
          options={SECTOR_OPTIONS}
          selected={formData.sectors}
          disabled={!canEdit}
          onAdd={(value) => addValue("sectors", value)}
          onRemove={(value) => removeValue("sectors", value)}
        />

        <MultiAddSelect
          label="Functions"
          required
          placeholder="Add a function"
          hint="Select at least one function you specialize in."
          options={FUNCTION_OPTIONS}
          selected={formData.functions}
          disabled={!canEdit}
          onAdd={(value) => addValue("functions", value)}
          onRemove={(value) => removeValue("functions", value)}
        />

        <MultiAddSelect
          label="Jurisdictions"
          required
          placeholder="Add a jurisdiction"
          hint="Select each jurisdiction you operate in."
          options={JURISDICTION_OPTIONS}
          selected={formData.jurisdictions}
          disabled={!canEdit}
          onAdd={(value) => addValue("jurisdictions", value)}
          onRemove={(value) => removeValue("jurisdictions", value)}
        />

        <div className="flex gap-3 pt-4">
          {canEdit && (
            <>
              <Button
                type="button"
                variant="secondary"
                onClick={handleSaveDraft}
                disabled={saveDraftDisabled}
              >
                Save Draft
              </Button>
              <Button type="submit" disabled={submitDisabled} loading={loading}>
                Submit Application
              </Button>
            </>
          )}
        </div>
      </form>
    </div>
  );
}

/**
 * Dropdown that appends the chosen option to a list of selected values,
 * rendering each pick as a removable chip with its human-readable label.
 *
 * @param label - Field label; also used to associate the select for a11y.
 * @param required - When true, renders a red asterisk marking the field required.
 * @param placeholder - Prompt shown while nothing is being added.
 * @param hint - Short helper text under the label.
 * @param options - Available taxonomy options.
 * @param selected - Currently chosen backend values.
 * @param disabled - Disables the control (read-only application state).
 * @param onAdd - Called with the chosen value when an option is selected.
 * @param onRemove - Called with a value when its chip is dismissed.
 */
function MultiAddSelect({
  label,
  required = false,
  placeholder,
  hint,
  options,
  selected,
  disabled,
  onAdd,
  onRemove,
}: {
  label: string;
  required?: boolean;
  placeholder: string;
  hint: string;
  options: readonly { label: string; value: string }[];
  selected: string[];
  disabled?: boolean;
  onAdd: (value: string) => void;
  onRemove: (value: string) => void;
}) {
  const id = `attestor-${label.toLowerCase().replaceAll(" ", "-")}`;
  const labelOf = (value: string) =>
    options.find((option) => option.value === value)?.label ?? value;
  // Only offer options that have not already been picked.
  const available = options.filter((option) => !selected.includes(option.value));

  return (
    <div>
      <label htmlFor={id} className="mb-1 block text-sm font-semibold text-foreground">
        {label}
        {required && <RequiredMark />}
      </label>
      <p className="mb-2 text-xs text-foreground-muted">{hint}</p>

      {selected.length > 0 && (
        <div className="mb-2 flex flex-wrap gap-2">
          {selected.map((value) => (
            <span
              key={value}
              className="inline-flex items-center gap-2 rounded-lg border border-border-default bg-surface-2 px-3 py-1.5 text-sm text-foreground"
            >
              {labelOf(value)}
              {!disabled && (
                <button
                  type="button"
                  aria-label={`Remove ${labelOf(value)}`}
                  onMouseDown={(event) => {
                    event.preventDefault();
                  }}
                  onClick={() => onRemove(value)}
                  className="m-0 cursor-pointer appearance-none border-0 bg-transparent p-0 text-base leading-none text-foreground-muted shadow-none outline-none [-webkit-tap-highlight-color:transparent] hover:text-foreground focus:outline-none focus-visible:outline-none"
                >
                  ×
                </button>
              )}
            </span>
          ))}
        </div>
      )}

      <div className="relative">
        <select
          id={id}
          disabled={disabled || available.length === 0}
          value=""
          onChange={(event) => {
            if (event.target.value) onAdd(event.target.value);
          }}
          className="min-h-12 w-full cursor-pointer appearance-none rounded-xl border border-border-default bg-background pl-4 pr-10 text-sm text-foreground outline-none transition-all focus:border-accent focus:ring-0 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <option value="" disabled hidden>
            {available.length === 0 ? "All added" : placeholder}
          </option>
          {available.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center px-3 text-foreground-muted">
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
          </svg>
        </div>
      </div>
    </div>
  );
}
