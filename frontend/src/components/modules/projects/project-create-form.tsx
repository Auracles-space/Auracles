"use client";

/**
 * Operator Project creation form.
 *
 * Creates the Project through the generated client and redirects to the
 * workspace shell once the backend accepts it.
 */
import { useRouter } from "next/navigation";
import { useId, useState } from "react";

import {
  configureBrowserClient,
  describeGeneratedError,
} from "@/lib/auth/form-client";
import { allValid, isNonEmpty, isPositiveNumber } from "@/lib/forms/validators";
import { projectApi, type ProjectApiMode } from "@/lib/projects/project-api-mode";
import type { ProjectCreateRequest } from "@/lib/generated/types.gen";
import { FUNCTION_OPTIONS } from "@/lib/marketplace/taxonomy";
import { currencySymbol, PLATFORM_CURRENCY } from "@/lib/marketplace/currency";

type ProjectFormState = {
  budgetMax: string;
  budgetMin: string;
  category: string;
  deadline: string;
  deliverableDescription: string;
  deliverableName: string;
  description: string;
  title: string;
};

const initialState: ProjectFormState = {
  budgetMax: "",
  budgetMin: "",
  category: "",
  deadline: "",
  deliverableDescription: "",
  deliverableName: "",
  description: "",
  title: "",
};

/**
 * Render a compact label and input pair.
 *
 * `prefix` renders a leading adornment inside the field — the currency symbol
 * on the budget inputs, so the unit sits where the number is typed rather than
 * in the label, which keeps the label stable for screen readers and tests.
 */
function TextField({
  label,
  min,
  onChange,
  placeholder,
  prefix,
  required = false,
  type = "text",
  value,
}: {
  label: string;
  min?: string;
  onChange: (value: string) => void;
  placeholder?: string;
  prefix?: string;
  required?: boolean;
  type?: string;
  value: string;
}) {
  // Associated by id rather than by wrapping, because a wrapping label absorbs
  // the adornment into the field's accessible name — "Minimum budget ₦"
  // instead of "Minimum budget".
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
          className={`min-h-12 w-full rounded-xl border border-border-default bg-surface-2 text-sm text-foreground outline-none transition-all focus:border-accent focus:ring-0 placeholder:text-foreground-muted/50 ${
            prefix ? "pl-10 pr-4" : "px-4"
          }`}
          id={fieldId}
          min={min}
          onChange={(event) => onChange(event.target.value)}
          placeholder={placeholder}
          required={required}
          type={type}
          value={value}
        />
      </div>
    </div>
  );
}

/**
 * Render the Project creation form.
 */
export function ProjectCreateForm({ mode = { kind: "self" } }: { mode?: ProjectApiMode }) {
  const router = useRouter();
  const [form, setForm] = useState<ProjectFormState>(initialState);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const today = new Date().toISOString().split("T")[0];
  const isPastDeadline = form.deadline ? form.deadline < today : false;

  const isValidBudget =
    isPositiveNumber(form.budgetMin) &&
    isPositiveNumber(form.budgetMax) &&
    Number(form.budgetMin) <= Number(form.budgetMax);

  const canSubmit = allValid(
    isNonEmpty(form.title),
    isNonEmpty(form.description),
    isNonEmpty(form.category),
    isValidBudget,
    isNonEmpty(form.deliverableName),
    isNonEmpty(form.deliverableDescription),
    !isPastDeadline,
  );

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    configureBrowserClient();

    const body: ProjectCreateRequest = {
      budget_max: form.budgetMax,
      budget_min: form.budgetMin,
      category: form.category,
      currency: PLATFORM_CURRENCY,
      deadline: form.deadline || null,
      description: form.description,
      required_deliverables: [
        {
          description: form.deliverableDescription,
          name: form.deliverableName,
        },
      ],
      title: form.title,
    };

    const result = await projectApi(mode).createProject(body);
    setSaving(false);
    if (!result.response.ok || !result.data) {
      setError(describeGeneratedError(result.error));
      return;
    }
    const workspacePath =
      mode.kind === "org"
        ? `/dashboard/organizations/${mode.orgId}/projects/${result.data.id}`
        : `/projects/${result.data.id}`;
    router.push(workspacePath);
  }

  return (
    <form className="grid gap-5" onSubmit={handleSubmit}>
      <TextField
        label="Title"
        onChange={(title) => setForm((current) => ({ ...current, title }))}
        placeholder="e.g. Migrate billing to Stripe"
        required
        value={form.title}
      />
      <label className="block">
        <span className="mb-1.5 block text-sm font-semibold text-foreground">
          Description
        </span>
        <textarea
          className="min-h-32 w-full rounded-xl border border-border-default bg-surface-2 px-4 py-3 text-sm text-foreground outline-none transition-all focus:border-accent focus:ring-0 placeholder:text-foreground-muted/50"
          onChange={(event) =>
            setForm((current) => ({
              ...current,
              description: event.target.value,
            }))
          }
          placeholder="Describe the scope, requirements, and deliverables of this project..."
          required
          value={form.description}
        />
      </label>
      <div className="grid gap-5 md:grid-cols-3">
        <label className="block">
          <span className="mb-1.5 block text-sm font-semibold text-foreground">
            Category
          </span>
          <select
            className="min-h-12 w-full rounded-xl border border-border-default bg-surface-2 px-4 text-sm text-foreground outline-none transition-all focus:border-accent focus:ring-0"
            onChange={(event) =>
              setForm((current) => ({ ...current, category: event.target.value }))
            }
            required
            value={form.category}
          >
            <option disabled value="">
              Select a category
            </option>
            {FUNCTION_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <TextField
          label="Minimum budget"
          onChange={(budgetMin) =>
            setForm((current) => ({ ...current, budgetMin }))
          }
          placeholder="e.g. 500000"
          prefix={currencySymbol(PLATFORM_CURRENCY)}
          required
          value={form.budgetMin}
        />
        <TextField
          label="Maximum budget"
          onChange={(budgetMax) =>
            setForm((current) => ({ ...current, budgetMax }))
          }
          placeholder="e.g. 2000000"
          prefix={currencySymbol(PLATFORM_CURRENCY)}
          required
          value={form.budgetMax}
        />
      </div>
      {Number(form.budgetMin) > Number(form.budgetMax) &&
      isPositiveNumber(form.budgetMin) &&
      isPositiveNumber(form.budgetMax) ? (
        <p className="text-xs text-[#DC2626]">
          Maximum budget must be greater than or equal to minimum budget.
        </p>
      ) : null}
      <div className="grid gap-5 md:grid-cols-2">
        <TextField
          label="Deliverable name"
          onChange={(deliverableName) =>
            setForm((current) => ({ ...current, deliverableName }))
          }
          placeholder="e.g. Implementation playbook"
          required
          value={form.deliverableName}
        />
        <div className="flex flex-col gap-1.5">
          <TextField
            label="Deadline"
            min={today}
            onChange={(deadline) => setForm((current) => ({ ...current, deadline }))}
            type="date"
            value={form.deadline}
          />
          {isPastDeadline ? (
            <p className="text-xs text-[#DC2626]">
              Deadline cannot be in the past.
            </p>
          ) : null}
        </div>
      </div>
      <label className="block">
        <span className="mb-1.5 block text-sm font-semibold text-foreground">
          Deliverable description
        </span>
        <textarea
          className="min-h-24 w-full rounded-xl border border-border-default bg-surface-2 px-4 py-3 text-sm text-foreground outline-none transition-all focus:border-accent focus:ring-0 placeholder:text-foreground-muted/50"
          onChange={(event) =>
            setForm((current) => ({
              ...current,
              deliverableDescription: event.target.value,
            }))
          }
          placeholder="Describe the expected deliverable details and format..."
          required
          value={form.deliverableDescription}
        />
      </label>
      {error ? (
        <p className="rounded-xl border border-[#DC2626]/30 bg-[#DC2626]/10 p-3 text-sm text-[#DC2626]">
          {error}
        </p>
      ) : null}
      <div className="flex justify-end">
        <button
          className="inline-flex min-h-12 items-center justify-center rounded-xl bg-foreground px-5 text-sm font-semibold text-background shadow-sm outline-none transition-all hover:bg-foreground/90 focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-60 disabled:cursor-not-allowed"
          disabled={saving || !canSubmit}
          type="submit"
        >
          {saving ? "Posting Project" : "Post project"}
        </button>
      </div>
    </form>
  );
}
