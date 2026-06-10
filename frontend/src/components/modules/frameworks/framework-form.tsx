"use client";

/**
 * Contributor Framework metadata form.
 *
 * Used for both draft creation and draft updates; service calls stay in parent
 * components so this form remains a reusable UI unit.
 */
import { useState } from "react";

import type {
  FrameworkCreate,
  FrameworkResponse,
  PricingConfig,
} from "@/lib/generated/types.gen";
import {
  FRAMEWORK_CATEGORY_OPTIONS,
  FUNCTION_OPTIONS,
  INDUSTRY_OPTIONS,
  ORG_SIZE_OPTIONS,
  SECTOR_OPTIONS,
  type MarketplaceOption,
} from "@/lib/marketplace/taxonomy";

type FrameworkFormProps = {
  framework?: FrameworkResponse;
  prefill?: FrameworkDraftPrefill;
  onSubmit: (payload: FrameworkCreate) => Promise<void>;
  submitLabel?: string;
};

export type FrameworkDraftPrefill = {
  description?: string;
  fileKeys?: string[];
  tags?: string[];
  title?: string;
};

type FrameworkFormState = {
  category: FrameworkCreate["category"];
  description: string;
  function: NonNullable<FrameworkCreate["function"]>;
  industry: NonNullable<FrameworkCreate["industry"]>;
  orgSize: NonNullable<FrameworkCreate["org_size"]>;
  price: string;
  sector: NonNullable<FrameworkCreate["sector"]>;
  tags: string;
  title: string;
};

/**
 * Return a known taxonomy value, falling back for legacy records.
 *
 * @param value - Persisted value from an existing Framework.
 * @param options - Allowed canonical values for the select.
 */
function coerceTaxonomyValue<TValue extends string>(
  value: string | null | undefined,
  options: readonly MarketplaceOption<TValue>[],
): TValue {
  const match = options.find((option) => option.value === value);
  return match?.value ?? options[0].value;
}

/**
 * Render a Framework create/edit form.
 *
 * @param props - Optional existing Framework and async submit callback.
 */
export function FrameworkForm({
  framework,
  prefill,
  onSubmit,
  submitLabel = "Save framework",
}: FrameworkFormProps) {
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState<FrameworkFormState>({
    category: coerceTaxonomyValue(framework?.category, FRAMEWORK_CATEGORY_OPTIONS),
    description: framework?.description ?? prefill?.description ?? "",
    function: coerceTaxonomyValue(framework?.function, FUNCTION_OPTIONS),
    industry: coerceTaxonomyValue(framework?.industry, INDUSTRY_OPTIONS),
    orgSize: coerceTaxonomyValue(framework?.org_size, ORG_SIZE_OPTIONS),
    price: framework?.pricing.price ?? "250",
    sector: coerceTaxonomyValue(framework?.sector, SECTOR_OPTIONS),
    tags: framework?.tags.join(", ") ?? prefill?.tags?.join(", ") ?? "",
    title: framework?.title ?? prefill?.title ?? "",
  });

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setSaving(true);

    const pricing: PricingConfig = {
      currency: framework?.pricing.currency ?? "USD",
      license_types: framework?.pricing.license_types ?? ["single_user", "team"],
      price: form.price,
    };

    try {
      await onSubmit({
        category: form.category,
        description: form.description,
        function: form.function,
        industry: form.industry,
        org_size: form.orgSize,
        pricing,
        sector: form.sector,
        tags: form.tags
          .split(",")
          .map((tag) => tag.trim())
          .filter(Boolean),
        title: form.title,
      });
    } catch (submitError) {
      setError(
        submitError instanceof Error
          ? submitError.message
          : "Framework could not be saved.",
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <form className="grid gap-6" onSubmit={handleSubmit}>
      <FormTextInput
        label="Framework Title"
        placeholder="e.g. Enterprise React Architecture Template"
        onChange={(value) => setForm((current) => ({ ...current, title: value }))}
        required
        value={form.title}
        helperText="A clear, specific title helps operators find exactly what they need."
      />
      
      <label className="block">
        <span className="mb-1.5 block text-sm font-semibold text-foreground">
          Description
        </span>
        <textarea
          placeholder="Describe what your framework includes, the problem it solves, and who it's for..."
          className="min-h-32 w-full rounded-xl border border-border-default bg-background px-4 py-3 text-sm text-foreground outline-none transition-all focus:border-accent focus:ring-0 placeholder:text-foreground-muted/50 resize-y"
          onChange={(event) =>
            setForm((current) => ({
              ...current,
              description: event.target.value,
            }))
          }
          required
          value={form.description}
        />
      </label>

      <div className="grid gap-6 sm:grid-cols-2">
        <FormSelectInput
          label="Sector"
          onChange={(value) => setForm((current) => ({ ...current, sector: value }))}
          options={SECTOR_OPTIONS}
          required
          value={form.sector}
        />
        <FormSelectInput
          label="Industry"
          onChange={(value) =>
            setForm((current) => ({ ...current, industry: value }))
          }
          options={INDUSTRY_OPTIONS}
          required
          value={form.industry}
        />
        <FormSelectInput
          label="Function"
          onChange={(value) =>
            setForm((current) => ({ ...current, function: value }))
          }
          options={FUNCTION_OPTIONS}
          required
          value={form.function}
        />
        <FormSelectInput
          label="Category"
          onChange={(value) =>
            setForm((current) => ({ ...current, category: value }))
          }
          options={FRAMEWORK_CATEGORY_OPTIONS}
          required
          value={form.category}
        />
        <FormSelectInput
          label="Organization Size"
          onChange={(value) => setForm((current) => ({ ...current, orgSize: value }))}
          options={ORG_SIZE_OPTIONS}
          required
          value={form.orgSize}
        />
        
        <label className="block">
          <span className="mb-1.5 block text-sm font-semibold text-foreground">
            Base Price
          </span>
          <div className="relative">
            <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-4 text-foreground-muted">
              <span className="text-sm font-medium">$</span>
            </div>
            <input
              type="text"
              placeholder="250"
              className="h-11 w-full rounded-xl border border-border-default bg-background pl-8 pr-4 text-sm text-foreground outline-none transition-all focus:border-accent focus:ring-0 placeholder:text-foreground-muted/50"
              onChange={(event) => setForm((current) => ({ ...current, price: event.target.value }))}
              required
              value={form.price}
            />
            <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center pr-4 text-foreground-muted">
              <span className="text-xs uppercase">USD</span>
            </div>
          </div>
        </label>
      </div>

      <FormTextInput
        label="Tags"
        placeholder="e.g. python, standard-operating-procedure, aws (comma separated)"
        onChange={(value) => setForm((current) => ({ ...current, tags: value }))}
        value={form.tags}
        helperText="Add up to 5 tags to help index your framework in the marketplace."
      />

      {prefill?.fileKeys?.length ? (
        <div className="rounded-lg border border-border-default bg-surface-2 p-4 text-sm text-foreground">
          <p className="font-semibold">Source files</p>
          <ul className="mt-2 grid gap-1 text-xs text-foreground-muted">
            {prefill.fileKeys.map((fileKey) => (
              <li className="truncate" key={fileKey}>
                {fileKey}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {error ? (
        <div className="rounded-lg bg-error/10 p-3 border border-error/20 flex items-center gap-2 text-sm text-error">
          <svg className="h-4 w-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          {error}
        </div>
      ) : null}
      
      <div className="mt-4 pt-6 border-t border-border-default flex items-center justify-end">
        <button
          className="inline-flex h-11 items-center justify-center rounded-xl bg-foreground px-8 text-sm font-semibold text-background shadow-sm outline-none transition-all hover:bg-foreground/90 focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-60 disabled:cursor-not-allowed"
          disabled={saving}
          type="submit"
        >
          {saving ? (
            <>
              <svg className="animate-spin -ml-1 mr-2 h-4 w-4 text-background" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
              </svg>
              Creating draft...
            </>
          ) : (
            submitLabel
          )}
        </button>
      </div>
    </form>
  );
}

type FormSelectInputProps<TValue extends string> = {
  label: string;
  onChange: (value: TValue) => void;
  options: readonly MarketplaceOption<TValue>[];
  required?: boolean;
  value: TValue;
};

/**
 * Render one taxonomy select field.
 *
 * @param props - Label, selected value, options, and change handler.
 */
function FormSelectInput<TValue extends string>({
  label,
  onChange,
  options,
  required = false,
  value,
}: FormSelectInputProps<TValue>) {
  const inputId = `framework-${label.toLowerCase().replaceAll(" ", "-")}`;

  return (
    <div className="block">
      <label
        className="mb-1.5 block text-sm font-semibold text-foreground"
        htmlFor={inputId}
      >
        {label}
        {required && (
          <span aria-hidden="true" className="ml-1 text-accent">
            *
          </span>
        )}
      </label>
      <div className="relative">
        <select
          className="h-11 w-full appearance-none rounded-xl border border-border-default bg-background pl-4 pr-10 text-sm text-foreground outline-none transition-all focus:border-accent focus:ring-0"
          id={inputId}
          onChange={(event) => onChange(event.target.value as TValue)}
          required={required}
          value={value}
        >
          {options.map((option) => (
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

type FormTextInputProps = {
  label: string;
  onChange: (value: string) => void;
  required?: boolean;
  value: string;
  placeholder?: string;
  helperText?: string;
};

/**
 * Render one Brand Book text input.
 *
 * @param props - Label, value, change handler, placeholder, and helper text.
 */
function FormTextInput({
  label,
  onChange,
  required = false,
  value,
  placeholder,
  helperText,
}: FormTextInputProps) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-sm font-semibold text-foreground">
        {label}
        {required && (
          <span aria-hidden="true" className="ml-1 text-accent">
            *
          </span>
        )}
      </span>
      <input
        className="h-11 w-full rounded-xl border border-border-default bg-background px-4 text-sm text-foreground outline-none transition-all focus:border-accent focus:ring-0 placeholder:text-foreground-muted/50"
        onChange={(event) => onChange(event.target.value)}
        required={required}
        value={value}
        placeholder={placeholder}
      />
      {helperText && (
        <span className="mt-1.5 block text-xs text-foreground-muted">
          {helperText}
        </span>
      )}
    </label>
  );
}
