"use client";

/**
 * Operator Project edit form.
 *
 * Loads one open Project, lets its Operator correct it, and sends only the
 * fields that actually changed. The sparse payload is deliberate: a full-body
 * PATCH would resend the budget untouched, which the backend refuses once a
 * Contributor has bid, and would overwrite anything a concurrent session had
 * just changed.
 *
 * Budget and required deliverables are the terms a Proposal is priced against,
 * so they are closed off while any Proposal is pending rather than offered and
 * then rejected with a 409.
 *
 * Maps to: FR-PROJ-003 (Operator edits an open Project).
 */
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useId, useMemo, useState } from "react";

import {
  configureBrowserClient,
  describeGeneratedError,
} from "@/lib/auth/form-client";
import { allValid, isNonEmpty, isPositiveNumber } from "@/lib/forms/validators";
import type { ProposalResponse } from "@/lib/generated/types.gen";
import { currencySymbol } from "@/lib/marketplace/currency";
import { FUNCTION_OPTIONS } from "@/lib/marketplace/taxonomy";
import { projectApi, type ProjectApiMode } from "@/lib/projects/project-api-mode";

/** One required deliverable as the form holds it. */
type DeliverableDraft = {
  description: string;
  name: string;
};

type ProjectEditState = {
  budgetMax: string;
  budgetMin: string;
  category: string;
  deadline: string;
  deliverables: DeliverableDraft[];
  description: string;
  title: string;
};

/**
 * Normalise the API's deliverable list into the form's own shape.
 *
 * The response types them as an open record, and the comparison that decides
 * whether to send them depends on a stable key order, so both the baseline and
 * the edited value are built through here.
 *
 * @param raw - `required_deliverables` as the API returned it.
 * @returns Name/description pairs, always in that key order.
 */
function toDrafts(raw: Array<Record<string, unknown>>): DeliverableDraft[] {
  return raw.map((entry) => ({
    name: typeof entry.name === "string" ? entry.name : "",
    description:
      typeof entry.description === "string" ? entry.description : "",
  }));
}

/** Serialise drafts for both the comparison and the request body. */
function fromDrafts(drafts: DeliverableDraft[]): Array<DeliverableDraft> {
  return drafts.map((draft) => ({
    description: draft.description,
    name: draft.name,
  }));
}

/**
 * Render a labelled field with an optional leading adornment.
 *
 * Associated by id rather than by wrapping, because a wrapping label absorbs
 * the adornment into the field's accessible name.
 */
function Field({
  disabled = false,
  label,
  min,
  onChange,
  placeholder,
  prefix,
  type = "text",
  value,
}: {
  disabled?: boolean;
  label: string;
  min?: string;
  onChange: (value: string) => void;
  placeholder?: string;
  prefix?: string;
  type?: string;
  value: string;
}) {
  const fieldId = useId();
  return (
    <div className="block">
      <label
        className="mb-1.5 block text-sm font-semibold text-foreground"
        htmlFor={fieldId}
      >
        {label}
      </label>
      <div className="relative">
        {prefix ? (
          <span className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-sm text-foreground-muted">
            {prefix}
          </span>
        ) : null}
        <input
          className={`min-h-12 w-full rounded-xl border border-border-default bg-surface-2 text-sm text-foreground outline-none transition-all focus:border-accent focus:ring-0 placeholder:text-foreground-muted/50 disabled:cursor-not-allowed disabled:opacity-60 ${
            prefix ? "pl-10 pr-4" : "px-4"
          }`}
          disabled={disabled}
          id={fieldId}
          min={min}
          onChange={(event) => onChange(event.target.value)}
          placeholder={placeholder}
          type={type}
          value={value}
        />
      </div>
    </div>
  );
}

/**
 * Render the Project edit form for one Project.
 *
 * @param mode - Individual or organization identity the Project belongs to.
 * @param projectId - Project being edited.
 */
export function ProjectEditForm({
  mode = { kind: "self" },
  projectId,
}: {
  mode?: ProjectApiMode;
  projectId: string;
}) {
  const router = useRouter();
  const [form, setForm] = useState<ProjectEditState | null>(null);
  const [baseline, setBaseline] = useState<ProjectEditState | null>(null);
  const [termsLocked, setTermsLocked] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const workspacePath =
    mode.kind === "org"
      ? `/dashboard/organizations/${mode.orgId}/projects/${projectId}`
      : `/projects/${projectId}`;

  const today = new Date().toISOString().split("T")[0];
  const api = useMemo(() => projectApi(mode), [mode]);

  const load = useCallback(async () => {
    configureBrowserClient();
    const [project, proposals] = await Promise.all([
      api.getProject(projectId),
      api.listProjectProposals(projectId),
    ]);
    if (!project.response.ok || !project.data) {
      setLoadError(describeGeneratedError(project.error));
      return;
    }
    const loaded: ProjectEditState = {
      budgetMax: project.data.budget_max,
      budgetMin: project.data.budget_min,
      category: project.data.category,
      deadline: project.data.deadline ?? "",
      deliverables: toDrafts(project.data.required_deliverables ?? []),
      description: project.data.description,
      title: project.data.title,
    };
    setForm(loaded);
    setBaseline(loaded);
    // A proposals read the caller is not entitled to must not be mistaken for
    // "no bids" — that would unlock the very fields the bid protects. Only an
    // answered list can clear the lock.
    if (proposals.response.ok && proposals.data) {
      const rows: ProposalResponse[] = proposals.data.proposals ?? [];
      setTermsLocked(rows.some((proposal) => proposal.status === "pending"));
    } else {
      setTermsLocked(true);
    }
  }, [api, projectId]);

  useEffect(() => {
    void load();
  }, [load]);

  const isPastDeadline = form?.deadline ? form.deadline < today : false;
  const isValidBudget = form
    ? isPositiveNumber(form.budgetMin) &&
      isPositiveNumber(form.budgetMax) &&
      Number(form.budgetMin) <= Number(form.budgetMax)
    : false;

  /** Collect only the fields whose value differs from what was loaded. */
  const changes = useMemo(() => {
    if (!form || !baseline) {
      return {};
    }
    const body: Record<string, unknown> = {};
    if (form.title !== baseline.title) {
      body.title = form.title;
    }
    if (form.description !== baseline.description) {
      body.description = form.description;
    }
    if (form.category !== baseline.category) {
      body.category = form.category;
    }
    if (form.budgetMin !== baseline.budgetMin) {
      body.budget_min = form.budgetMin;
    }
    if (form.budgetMax !== baseline.budgetMax) {
      body.budget_max = form.budgetMax;
    }
    if (form.deadline !== baseline.deadline) {
      body.deadline = form.deadline || null;
    }
    if (
      JSON.stringify(fromDrafts(form.deliverables)) !==
      JSON.stringify(fromDrafts(baseline.deliverables))
    ) {
      body.required_deliverables = fromDrafts(form.deliverables);
    }
    return body;
  }, [baseline, form]);

  const hasChanges = Object.keys(changes).length > 0;
  const canSubmit =
    form !== null &&
    hasChanges &&
    !saving &&
    allValid(
      isNonEmpty(form.title),
      isNonEmpty(form.description),
      isNonEmpty(form.category),
      isValidBudget,
      !isPastDeadline,
      form.deliverables.every(
        (draft) => isNonEmpty(draft.name) && isNonEmpty(draft.description),
      ),
    );

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canSubmit) {
      return;
    }
    setSaving(true);
    setError(null);
    const result = await api.updateProject(projectId, changes);
    setSaving(false);
    if (!result.response.ok || !result.data) {
      setError(describeGeneratedError(result.error));
      return;
    }
    router.push(workspacePath);
  }

  if (loadError) {
    return (
      <p className="rounded-xl border border-[#DC2626]/30 bg-[#DC2626]/10 p-3 text-sm text-[#DC2626]">
        {loadError}
      </p>
    );
  }

  if (!form) {
    return (
      <p className="text-sm text-foreground-muted">Loading this Project…</p>
    );
  }

  return (
    <form className="grid gap-5" onSubmit={handleSubmit}>
      <Field
        label="Title"
        onChange={(title) => setForm((current) => current && { ...current, title })}
        value={form.title}
      />
      <div className="block">
        <label
          className="mb-1.5 block text-sm font-semibold text-foreground"
          htmlFor="project-edit-description"
        >
          Description
        </label>
        <textarea
          className="min-h-32 w-full rounded-xl border border-border-default bg-surface-2 px-4 py-3 text-sm text-foreground outline-none transition-all focus:border-accent focus:ring-0 placeholder:text-foreground-muted/50"
          id="project-edit-description"
          onChange={(event) =>
            setForm(
              (current) =>
                current && { ...current, description: event.target.value },
            )
          }
          value={form.description}
        />
      </div>
      <div className="grid gap-5 md:grid-cols-3">
        <div className="block">
          <label
            className="mb-1.5 block text-sm font-semibold text-foreground"
            htmlFor="project-edit-category"
          >
            Category
          </label>
          <select
            className="min-h-12 w-full rounded-xl border border-border-default bg-surface-2 px-4 text-sm text-foreground outline-none transition-all focus:border-accent focus:ring-0"
            id="project-edit-category"
            onChange={(event) =>
              setForm(
                (current) =>
                  current && { ...current, category: event.target.value },
              )
            }
            value={form.category}
          >
            {FUNCTION_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
        <Field
          disabled={termsLocked}
          label="Minimum budget"
          onChange={(budgetMin) =>
            setForm((current) => current && { ...current, budgetMin })
          }
          prefix={currencySymbol()}
          value={form.budgetMin}
        />
        <Field
          disabled={termsLocked}
          label="Maximum budget"
          onChange={(budgetMax) =>
            setForm((current) => current && { ...current, budgetMax })
          }
          prefix={currencySymbol()}
          value={form.budgetMax}
        />
      </div>
      {termsLocked ? (
        <p className="rounded-xl border border-[#F59E0B]/30 bg-[#F59E0B]/10 p-3 text-sm text-foreground-muted">
          Budget and deliverables cannot change while a Proposal is pending —
          they are the terms Contributors priced against. Decline the
          outstanding Proposals first, or edit the title, description, category
          or deadline.
        </p>
      ) : null}
      {!isValidBudget && !termsLocked ? (
        <p className="text-xs text-[#DC2626]">
          Maximum budget must be greater than or equal to minimum budget, and
          both must be above zero.
        </p>
      ) : null}
      <div className="grid gap-1.5 md:max-w-xs">
        <Field
          label="Deadline"
          min={today}
          onChange={(deadline) =>
            setForm((current) => current && { ...current, deadline })
          }
          type="date"
          value={form.deadline}
        />
        {isPastDeadline ? (
          <p className="text-xs text-[#DC2626]">
            Deadline cannot be in the past.
          </p>
        ) : null}
      </div>
      <div className="grid gap-3 rounded-xl border border-border-default bg-surface-2 p-4">
        <p className="text-sm font-semibold text-foreground">
          Required deliverables
        </p>
        {form.deliverables.map((draft, index) => (
          <div className="grid gap-3 md:grid-cols-2" key={index}>
            <Field
              disabled={termsLocked}
              label={`Deliverable name ${index + 1}`}
              onChange={(name) =>
                setForm(
                  (current) =>
                    current && {
                      ...current,
                      deliverables: current.deliverables.map((entry, position) =>
                        position === index ? { ...entry, name } : entry,
                      ),
                    },
                )
              }
              value={draft.name}
            />
            <Field
              disabled={termsLocked}
              label={`Deliverable description ${index + 1}`}
              onChange={(description) =>
                setForm(
                  (current) =>
                    current && {
                      ...current,
                      deliverables: current.deliverables.map((entry, position) =>
                        position === index ? { ...entry, description } : entry,
                      ),
                    },
                )
              }
              value={draft.description}
            />
          </div>
        ))}
      </div>
      {error ? (
        <p className="rounded-xl border border-[#DC2626]/30 bg-[#DC2626]/10 p-3 text-sm text-[#DC2626]">
          {error}
        </p>
      ) : null}
      <div className="flex flex-wrap justify-end gap-3">
        <button
          className="inline-flex min-h-12 items-center justify-center rounded-xl border border-border-default bg-surface-1 px-5 text-sm font-semibold text-foreground outline-none transition-all hover:bg-surface-2 focus-visible:ring-2 focus-visible:ring-accent"
          onClick={() => router.push(workspacePath)}
          type="button"
        >
          Cancel
        </button>
        <button
          className="inline-flex min-h-12 items-center justify-center rounded-xl bg-foreground px-5 text-sm font-semibold text-background shadow-sm outline-none transition-all hover:bg-foreground/90 focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-60"
          disabled={!canSubmit}
          type="submit"
        >
          {saving ? "Saving changes" : "Save changes"}
        </button>
      </div>
    </form>
  );
}
