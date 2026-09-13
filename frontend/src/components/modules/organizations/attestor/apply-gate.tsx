"use client";

import { useState } from "react";
import {
  createOrgAttestorApplication,
  updateOrgAttestorApplication,
} from "@/lib/generated/sdk.gen";
import type { OrgAttestorApplicationResponse } from "@/lib/generated/types.gen";
import { describeGeneratedError, getAccessTokenHeaders } from "@/lib/auth/form-client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { isLengthBetween } from "@/lib/forms/validators";
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
    credentials_summary: application?.credentials_summary || "",
    professional_references: application?.professional_references || "",
    sample_work_url: (application?.sample_work as { url: string })?.url || "",
    sectors: application?.sectors || [],
    functions: application?.functions || [],
    jurisdictions: application?.jurisdictions || [],
  });

  // Incorporation docs are server-owned (attached via the dedicated endpoint),
  // so read them from the live application, not editable form state.
  const isNew = !application;

  // Creating the draft row only needs the columns the create endpoint marks
  // required; legal_name, registration_number, and docs are attached afterward.
  const canCreate =
    isLengthBetween(formData.credentials_summary, 10, 5000) &&
    isLengthBetween(formData.professional_references, 3, 5000) &&
    formData.sectors.length > 0 &&
    formData.functions.length > 0 &&
    formData.jurisdictions.length > 0;

  const saveDraftDisabled = loading || (isNew && !canCreate);

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

  /** Attach the selected incorporation document to the application. */

  return (
    <div className="rounded-xl border border-border-default bg-surface-1 p-5 shadow-sm">
      {error && (
        <div className="mb-6 rounded-lg border border-error/50 bg-error/5 p-4 text-sm text-error">
          {error}
        </div>
      )}

      <form onSubmit={(e) => e.preventDefault()} className="space-y-4">
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

        {/* Incorporation documents moved to the organization's
            verification page: they establish the org's legal identity for
            every capability, not just this application. */}

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

        {canEdit && (
          <div className="pt-4">
            <Button
              type="button"
              variant="secondary"
              onClick={handleSaveDraft}
              disabled={saveDraftDisabled}
              loading={loading}
            >
              Save Draft
            </Button>
          </div>
        )}
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
