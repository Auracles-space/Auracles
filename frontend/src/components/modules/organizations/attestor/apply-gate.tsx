"use client";

import { useState } from "react";
import {
  createOrgAttestorApplication,
  submitOrgAttestorApplication,
  updateOrgAttestorApplication,
} from "@/lib/generated/sdk.gen";
import type { OrgAttestorApplicationResponse } from "@/lib/generated/types.gen";
import { describeGeneratedError, getAccessTokenHeaders } from "@/lib/auth/form-client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { JURISDICTION_OPTIONS } from "@/lib/marketplace/taxonomy";

/** A selectable taxonomy value: `value` is submitted, `label` is displayed. */
type TaxonomyOption = { label: string; value: string };

/**
 * Attestor sector taxonomy. Values MUST equal the backend controlled set in
 * `attestation/taxonomy.py` (validated server-side); labels are display-only.
 */
const SECTOR_OPTIONS: readonly TaxonomyOption[] = [
  { label: "Private Equity", value: "PE" },
  { label: "Venture Capital", value: "VC" },
  { label: "Infrastructure", value: "Infrastructure" },
  { label: "Real Estate", value: "Real Estate" },
];

/**
 * Attestor framework-category taxonomy. Values MUST equal the backend
 * controlled set in `attestation/taxonomy.py`.
 */
const CATEGORY_OPTIONS: readonly TaxonomyOption[] = [
  { label: "Compliance", value: "Compliance" },
  { label: "Governance", value: "Governance" },
  { label: "Risk", value: "Risk" },
  { label: "Operations", value: "Operations" },
  { label: "Legal", value: "Legal" },
  { label: "Finance", value: "Finance" },
  { label: "HR", value: "HR" },
  { label: "Technology", value: "Technology" },
  { label: "Investment Management", value: "Investment Management" },
];

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

  const [formData, setFormData] = useState({
    legal_name: application?.legal_name || "",
    credentials_summary: application?.credentials_summary || "",
    professional_references: application?.professional_references || "",
    sample_work_url: (application?.sample_work as { url: string })?.url || "",
    incorporation_doc_keys: application?.incorporation_doc_keys || [],
    sectors: application?.sectors || [],
    framework_categories: application?.framework_categories || [],
    jurisdictions: application?.jurisdictions || [],
  });

  type ListField = "sectors" | "framework_categories" | "jurisdictions";

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
        credentials_summary: formData.credentials_summary,
        professional_references: formData.professional_references,
        sample_work: { url: formData.sample_work_url },
        incorporation_doc_keys: formData.incorporation_doc_keys,
        sectors: formData.sectors,
        framework_categories: formData.framework_categories,
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
        credentials_summary: formData.credentials_summary,
        professional_references: formData.professional_references,
        sample_work: { url: formData.sample_work_url },
        incorporation_doc_keys: formData.incorporation_doc_keys,
        sectors: formData.sectors,
        framework_categories: formData.framework_categories,
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

  return (
    <div className="rounded-xl border border-border-default bg-surface-1 p-5 shadow-sm">
      {isNeedsInfo && application?.admin_feedback && (
        <div className="mb-6 rounded-lg border border-warning/30 bg-warning/10 p-4 text-sm text-warning">
          <span className="mb-1 block font-bold">Admin Feedback:</span>
          {application.admin_feedback}
        </div>
      )}

      {error && (
        <div className="mb-6 rounded-lg border border-error/50 bg-error/5 p-4 text-sm text-error">
          {error}
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label htmlFor="legal_name" className="mb-1 block text-sm font-semibold text-foreground">
            Legal Name
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
            htmlFor="credentials_summary"
            className="mb-1 block text-sm font-semibold text-foreground"
          >
            Credentials Summary
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
          </label>
          <Textarea
            id="references"
            disabled={!canEdit}
            value={formData.professional_references}
            onChange={(e) => setFormData({ ...formData, professional_references: e.target.value })}
            placeholder="Names and contact info of references..."
          />
        </div>

        <MultiAddSelect
          label="Sectors"
          placeholder="Add a sector"
          hint="Select at least one sector your organization can attest."
          options={SECTOR_OPTIONS}
          selected={formData.sectors}
          disabled={!canEdit}
          onAdd={(value) => addValue("sectors", value)}
          onRemove={(value) => removeValue("sectors", value)}
        />

        <MultiAddSelect
          label="Framework Categories"
          placeholder="Add a category"
          hint="Select at least one category you specialize in."
          options={CATEGORY_OPTIONS}
          selected={formData.framework_categories}
          disabled={!canEdit}
          onAdd={(value) => addValue("framework_categories", value)}
          onRemove={(value) => removeValue("framework_categories", value)}
        />

        <MultiAddSelect
          label="Jurisdictions"
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
              <Button type="button" variant="secondary" onClick={handleSaveDraft} disabled={loading}>
                Save Draft
              </Button>
              <Button type="submit" disabled={loading} loading={loading}>
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
 * @param placeholder - Prompt shown while nothing is being added.
 * @param hint - Short helper text under the label.
 * @param options - Available taxonomy options ({@link TaxonomyOption}).
 * @param selected - Currently chosen backend values.
 * @param disabled - Disables the control (read-only application state).
 * @param onAdd - Called with the chosen value when an option is selected.
 * @param onRemove - Called with a value when its chip is dismissed.
 */
function MultiAddSelect({
  label,
  placeholder,
  hint,
  options,
  selected,
  disabled,
  onAdd,
  onRemove,
}: {
  label: string;
  placeholder: string;
  hint: string;
  options: readonly TaxonomyOption[];
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
                  onClick={() => onRemove(value)}
                  className="text-base leading-none text-foreground-muted hover:text-foreground"
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
          className="min-h-12 w-full appearance-none rounded-xl border border-border-default bg-background pl-4 pr-10 text-sm text-foreground outline-none transition-all focus:border-accent focus:ring-0 disabled:opacity-50"
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
