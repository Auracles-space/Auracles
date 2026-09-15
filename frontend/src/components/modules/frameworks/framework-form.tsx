"use client";

/**
 * Contributor Framework metadata form.
 *
 * Used for both draft creation and draft updates; service calls stay in parent
 * components so this form remains a reusable UI unit.
 */
import { ReactNode, useState } from "react";
import { Button } from "@/components/ui/button";

import { allValid, isNonEmpty, isPositiveNumber } from "@/lib/forms/validators";
import {
  PLATFORM_CURRENCY,
  currencySymbol,
} from "@/lib/marketplace/currency";
import type {
  FrameworkCreate,
  FrameworkResponse,
  PricingConfig,
} from "@/lib/generated/types.gen";
import {
  COMPLEXITY_OPTIONS,
  FRAMEWORK_CATEGORY_OPTIONS,
  FUNCTION_OPTIONS,
  INDUSTRY_OPTIONS,
  JURISDICTION_OPTIONS,
  LIFECYCLE_STAGE_OPTIONS,
  ORG_SIZE_OPTIONS,
  SECTOR_OPTIONS,
  type MarketplaceOption,
} from "@/lib/marketplace/taxonomy";

type LicenseTypeValue = "single_user" | "team" | "organizational" | "enterprise";

/**
 * Selectable license tiers, in canonical display + serialization order.
 *
 * The platform currently only supports single-user licensing. The team,
 * team, and enterprise tiers are intentionally commented out until multi-seat
 * licensing is ready.
 */
const LICENSE_TYPE_OPTIONS: readonly { value: LicenseTypeValue; label: string }[] =
  [
    { value: "single_user", label: "Single user" },
    { value: "organizational", label: "Organizational" },
    // { value: "team", label: "Team" },
    // { value: "enterprise", label: "Enterprise" },
  ];

/**
 * Constrain free text to a positive currency amount with at most two decimals.
 *
 * Strips any non-numeric characters, keeps a single decimal point, and caps the
 * fractional part at two digits so the value always matches the backend's
 * `decimal_places=2` pricing contract.
 *
 * @param raw - Raw input value from the price field.
 * @returns The sanitized amount string.
 */
function sanitizePriceInput(raw: string): string {
  const cleaned = raw.replace(/[^\d.]/g, "");
  const firstDot = cleaned.indexOf(".");
  if (firstDot === -1) {
    return cleaned;
  }
  const intPart = cleaned.slice(0, firstDot);
  const decPart = cleaned
    .slice(firstDot + 1)
    .replace(/\./g, "")
    .slice(0, 2);
  return `${intPart}.${decPart}`;
}

type FrameworkFormProps = {
  framework?: FrameworkResponse;
  prefill?: FrameworkDraftPrefill;
  onSubmit: (payload: FrameworkCreate) => Promise<void>;
  submitLabel?: string;
  leftActions?: ReactNode;
  children?: ReactNode;
  /**
   * Locks every metadata field and hides the save button. Used for statuses
   * the backend won't let a contributor edit in place (published, unpublished,
   * mid-pipeline); editing those requires starting a new version.
   */
  readOnly?: boolean;
  /** Render pricing and license fields inside this metadata form. */
  pricingInline?: boolean;
};

export type FrameworkDraftPrefill = {
  description?: string;
  fileKeys?: string[];
  tags?: string[];
  title?: string;
};

type FrameworkFormState = {
  category: FrameworkCreate["category"] | "";
  complexity: string;
  description: string;
  function: NonNullable<FrameworkCreate["function"]> | "";
  industry: NonNullable<FrameworkCreate["industry"]> | "";
  jurisdiction: string;
  licenseTypes: LicenseTypeValue[];
  lifecycleStage: string;
  orgSize: NonNullable<FrameworkCreate["org_size"]> | "";
  orgPrice: string;
  price: string;
  sector: NonNullable<FrameworkCreate["sector"]> | "";
  tags: string[];
  title: string;
};

/** Maximum number of marketplace tags allowed on a Framework. */
const MAX_TAGS = 5;

/**
 * Return a known taxonomy value, falling back for legacy records.
 *
 * @param value - Persisted value from an existing Framework.
 * @param options - Allowed canonical values for the select.
 */
function coerceTaxonomyValue<TValue extends string>(
  value: string | null | undefined,
  options: readonly MarketplaceOption<TValue>[],
): TValue | "" {
  const match = options.find((option) => option.value === value);
  return match?.value ?? "";
}

/**
 * Return a known value for an optional select, or "" when unset/unknown.
 *
 * Unlike `coerceTaxonomyValue`, optional metadata (complexity, lifecycle,
 * jurisdiction) has no required default — an empty string means "unspecified"
 * and is omitted from the submitted payload.
 *
 * @param value - Persisted value from an existing Framework.
 * @param options - Allowed canonical values for the select.
 */
function coerceOptionalValue(
  value: string | null | undefined,
  options: readonly MarketplaceOption[],
): string {
  return options.find((option) => option.value === value)?.value ?? "";
}

/**
 * Normalize persisted license types into known tiers in canonical order.
 *
 * Falls back to single-user for new drafts so the pricing contract always has
 * at least one tier.
 *
 * @param values - Persisted license types from an existing Framework.
 */
function coerceLicenseTypes(
  values: string[] | null | undefined,
): LicenseTypeValue[] {
  const selected = new Set(values ?? []);
  return LICENSE_TYPE_OPTIONS.map((option) => option.value).filter((value) =>
    selected.has(value),
  );
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
  leftActions,
  children,
  readOnly = false,
  pricingInline = true,
}: FrameworkFormProps) {
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const initialForm = (): FrameworkFormState => ({
    category: coerceTaxonomyValue(framework?.category, FRAMEWORK_CATEGORY_OPTIONS),
    complexity:
      framework?.complexity != null ? String(framework.complexity) : "",
    description: framework?.description ?? prefill?.description ?? "",
    function: coerceTaxonomyValue(framework?.function, FUNCTION_OPTIONS),
    industry: coerceTaxonomyValue(framework?.industry, INDUSTRY_OPTIONS),
    jurisdiction: coerceOptionalValue(framework?.jurisdiction, JURISDICTION_OPTIONS),
    licenseTypes: coerceLicenseTypes(framework?.pricing.license_types),
    lifecycleStage: coerceOptionalValue(
      framework?.lifecycle_stage,
      LIFECYCLE_STAGE_OPTIONS,
    ),
    orgSize: coerceTaxonomyValue(framework?.org_size, ORG_SIZE_OPTIONS),
    orgPrice:
      framework?.pricing.org_price != null
        ? String(framework.pricing.org_price)
        : "",
    price: framework?.pricing.price ?? "",
    sector: coerceTaxonomyValue(framework?.sector, SECTOR_OPTIONS),
    tags: (framework?.tags ?? prefill?.tags ?? []).slice(0, MAX_TAGS),
    title: framework?.title ?? prefill?.title ?? "",
  });
  const [form, setForm] = useState<FrameworkFormState>(initialForm);
  // The last values the server accepted. Editing an existing framework only
  // enables Save when something differs; a new framework has nothing saved.
  const [savedForm, setSavedForm] = useState<FrameworkFormState>(initialForm);
  const isDirty =
    !framework || JSON.stringify(form) !== JSON.stringify(savedForm);

  const canSubmit = allValid(
    isNonEmpty(form.title),
    isNonEmpty(form.description),
    !pricingInline || isPositiveNumber(form.price),
    !pricingInline || form.licenseTypes.length > 0,
    isNonEmpty(form.category),
    isNonEmpty(form.function),
    isNonEmpty(form.industry),
    isNonEmpty(form.sector),
    isNonEmpty(form.orgSize),
  );

  /** Toggle one license tier in the selection. */
  function toggleLicenseType(value: LicenseTypeValue): void {
    setForm((current) => {
      const selected = new Set(current.licenseTypes);
      if (selected.has(value)) {
        selected.delete(value);
      } else {
        selected.add(value);
      }
      return {
        ...current,
        licenseTypes: LICENSE_TYPE_OPTIONS.map((option) => option.value).filter(
          (option) => selected.has(option),
        ),
      };
    });
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setSaving(true);

    const submitted = form;
    const pricing: PricingConfig = {
      currency: framework?.pricing.currency ?? PLATFORM_CURRENCY,
      license_types: form.licenseTypes,
      org_price:
        form.licenseTypes.includes("organizational") && form.orgPrice.trim() !== ""
          ? form.orgPrice
          : null,
      price: form.price,
    };

    try {
      await onSubmit({
        category: form.category as FrameworkCreate["category"],
        description: form.description,
        function: form.function as NonNullable<FrameworkCreate["function"]>,
        industry: form.industry as NonNullable<FrameworkCreate["industry"]>,
        org_size: form.orgSize as NonNullable<FrameworkCreate["org_size"]>,
        pricing,
        sector: form.sector as NonNullable<FrameworkCreate["sector"]>,
        tags: form.tags.map((tag) => tag.trim()).filter(Boolean),
        title: form.title,
        // Optional metadata is only sent when chosen so unset selects stay null.
        ...(form.complexity ? { complexity: Number(form.complexity) } : {}),
        ...(form.lifecycleStage
          ? { lifecycle_stage: form.lifecycleStage }
          : {}),
        ...(form.jurisdiction ? { jurisdiction: form.jurisdiction } : {}),
      });
      setSavedForm(submitted);
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
      {/* `display: contents` keeps the grid gap intact while the disabled
          fieldset cascades the locked state to every inner control. */}
      <fieldset className="contents" disabled={readOnly}>
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
          emptyLabel="Select sector"
          onChange={(value) => setForm((current) => ({ ...current, sector: value }))}
          options={SECTOR_OPTIONS}
          required
          value={form.sector}
        />
        <FormSelectInput
          label="Industry"
          emptyLabel="Select industry"
          onChange={(value) =>
            setForm((current) => ({ ...current, industry: value }))
          }
          options={INDUSTRY_OPTIONS}
          required
          value={form.industry}
        />
        <FormSelectInput
          label="Function"
          emptyLabel="Select function"
          onChange={(value) =>
            setForm((current) => ({ ...current, function: value }))
          }
          options={FUNCTION_OPTIONS}
          required
          value={form.function}
        />
        <FormSelectInput
          label="Category"
          emptyLabel="Select category"
          onChange={(value) =>
            setForm((current) => ({ ...current, category: value }))
          }
          options={FRAMEWORK_CATEGORY_OPTIONS}
          required
          value={form.category}
        />
        <FormSelectInput
          label="Organization Size"
          emptyLabel="Select organization size"
          onChange={(value) => setForm((current) => ({ ...current, orgSize: value }))}
          options={ORG_SIZE_OPTIONS}
          required
          value={form.orgSize}
        />
        <FormOptionalSelectInput
          label="Complexity"
          emptyLabel="Any complexity"
          onChange={(value) =>
            setForm((current) => ({ ...current, complexity: value }))
          }
          options={COMPLEXITY_OPTIONS}
          value={form.complexity}
        />
        <FormOptionalSelectInput
          label="Lifecycle Stage"
          emptyLabel="Any stage"
          onChange={(value) =>
            setForm((current) => ({ ...current, lifecycleStage: value }))
          }
          options={LIFECYCLE_STAGE_OPTIONS}
          value={form.lifecycleStage}
        />
        <FormOptionalSelectInput
          label="Jurisdiction"
          emptyLabel="Any jurisdiction"
          onChange={(value) =>
            setForm((current) => ({ ...current, jurisdiction: value }))
          }
          options={JURISDICTION_OPTIONS}
          value={form.jurisdiction}
        />
      </div>

      {pricingInline ? (
        <>
          <fieldset className="block">
            <legend className="mb-1.5 block text-sm font-semibold text-foreground">
              License types
              <span aria-hidden="true" className="ml-1 text-accent">
                *
              </span>
            </legend>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              {LICENSE_TYPE_OPTIONS.map((option) => {
                const checked = form.licenseTypes.includes(option.value);
                return (
                  <label
                    key={option.value}
                    className={`flex min-h-12 cursor-pointer items-center gap-2 rounded-xl border px-4 text-sm font-medium transition-all ${
                      checked
                        ? "border-accent bg-accent/10 text-foreground"
                        : "border-border-default bg-surface-1 text-foreground-muted hover:border-accent/50 hover:bg-surface-2"
                    }`}
                  >
                    <input
                      type="checkbox"
                      className="h-4 w-4 shrink-0 accent-accent"
                      checked={checked}
                      onChange={() => toggleLicenseType(option.value)}
                    />
                    {option.label}
                  </label>
                );
              })}
            </div>
            <span className="mt-1.5 block text-xs text-foreground-muted">
              Choose at least one tier operators can license. Pricing scales per
              tier at checkout.
            </span>
          </fieldset>

          <div className="grid gap-6 sm:grid-cols-2">
            <label className="block">
              <span className="mb-1.5 block text-sm font-semibold text-foreground">
                Base Price
                <span aria-hidden="true" className="ml-1 text-accent">
                  *
                </span>
              </span>
              <div className="relative">
                <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-4 text-foreground-muted">
                  <span className="text-sm font-medium">{currencySymbol()}</span>
                </div>
                <input
                  type="text"
                  inputMode="decimal"
                  autoComplete="off"
                  placeholder="250.00"
                  className="min-h-12 w-full rounded-xl border border-border-default bg-background pl-8 pr-4 text-sm text-foreground outline-none transition-all focus:border-accent focus:ring-0 placeholder:text-foreground-muted/50"
                  onChange={(event) =>
                    setForm((current) => ({
                      ...current,
                      price: sanitizePriceInput(event.target.value),
                    }))
                  }
                  required
                  value={form.price}
                />
                <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center pr-4 text-foreground-muted">
                  <span className="text-xs uppercase">{PLATFORM_CURRENCY}</span>
                </div>
              </div>
            </label>

            {form.licenseTypes.includes("organizational") ? (
              <label className="block">
                <span className="mb-1.5 block text-sm font-semibold text-foreground">
                  Organization price
                </span>
                <div className="relative">
                  <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-4 text-foreground-muted">
                    <span className="text-sm font-medium">{currencySymbol()}</span>
                  </div>
                  <input
                    type="text"
                    inputMode="decimal"
                    autoComplete="off"
                    placeholder="Same as single-user price"
                    className="min-h-12 w-full rounded-xl border border-border-default bg-background pl-8 pr-4 text-sm text-foreground outline-none transition-all focus:border-accent focus:ring-0 placeholder:text-foreground-muted/50"
                    onChange={(event) =>
                      setForm((current) => ({
                        ...current,
                        orgPrice: sanitizePriceInput(event.target.value),
                      }))
                    }
                    value={form.orgPrice}
                  />
                  <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center pr-4 text-foreground-muted">
                    <span className="text-xs uppercase">{PLATFORM_CURRENCY}</span>
                  </div>
                </div>
                <span className="mt-1.5 block text-xs text-foreground-muted">
                  Leave blank to charge the same as the single-user price.
                </span>
              </label>
            ) : null}
          </div>
        </>
      ) : null}

      <TagChipInput
        label="Tags"
        max={MAX_TAGS}
        onChange={(value) => setForm((current) => ({ ...current, tags: value }))}
        value={form.tags}
      />

      {prefill?.fileKeys?.length ? (
        <div className="rounded-xl border border-border-default bg-surface-2 p-4 text-sm text-foreground">
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
        <div className="rounded-xl bg-error/10 p-3 border border-error/20 flex items-center gap-2 text-sm text-error">
          <svg className="h-4 w-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          {error}
        </div>
      ) : null}
      </fieldset>

      <div className="mt-4 pt-6 border-t border-border-default flex flex-wrap items-center justify-between gap-4">
        <div className="flex flex-wrap items-center gap-3">
          {leftActions}
        </div>
        <div className="flex flex-wrap items-center gap-3">
          {readOnly ? null : (
            <Button
              disabled={saving || !canSubmit || !isDirty}
              loading={saving}
              type="submit"
              variant={
                framework && (framework.status === "draft" || framework.status === "pipeline_passed" || framework.status === "pipeline_failed")
                  ? "secondary"
                  : "primary"
              }
            >
              {saving ? "Saving changes..." : submitLabel}
            </Button>
          )}
          {children}
        </div>
      </div>
    </form>
  );
}

type FormSelectInputProps<TValue extends string> = {
  label: string;
  emptyLabel?: string;
  onChange: (value: TValue) => void;
  options: readonly MarketplaceOption<TValue>[];
  required?: boolean;
  value: TValue | "";
};

/**
 * Render one taxonomy select field.
 *
 * @param props - Label, selected value, options, and change handler.
 */
function FormSelectInput<TValue extends string>({
  label,
  emptyLabel,
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
          className="min-h-12 w-full appearance-none rounded-xl border border-border-default bg-background pl-4 pr-10 text-sm text-foreground outline-none transition-all focus:border-accent focus:ring-0"
          id={inputId}
          onChange={(event) => onChange(event.target.value as TValue)}
          required={required}
          value={value}
        >
          {emptyLabel && (
            <option value="" disabled hidden={required}>
              {emptyLabel}
            </option>
          )}
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

type FormOptionalSelectInputProps = {
  label: string;
  emptyLabel: string;
  onChange: (value: string) => void;
  options: readonly MarketplaceOption[];
  value: string;
};

/**
 * Render an optional taxonomy select with a leading "unspecified" choice.
 *
 * The empty option carries value "" so the parent can omit the field from the
 * submitted payload, keeping complexity/lifecycle/jurisdiction nullable.
 *
 * @param props - Label, empty-choice label, options, value, and change handler.
 */
function FormOptionalSelectInput({
  label,
  emptyLabel,
  onChange,
  options,
  value,
}: FormOptionalSelectInputProps) {
  const inputId = `framework-${label.toLowerCase().replaceAll(" ", "-")}`;

  return (
    <div className="block">
      <label
        className="mb-1.5 block text-sm font-semibold text-foreground"
        htmlFor={inputId}
      >
        {label}
      </label>
      <div className="relative">
        <select
          className="min-h-12 w-full appearance-none rounded-xl border border-border-default bg-background pl-4 pr-10 text-sm text-foreground outline-none transition-all focus:border-accent focus:ring-0"
          id={inputId}
          onChange={(event) => onChange(event.target.value)}
          value={value}
        >
          <option value="">{emptyLabel}</option>
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
        className="min-h-12 w-full rounded-xl border border-border-default bg-background px-4 text-sm text-foreground outline-none transition-all focus:border-accent focus:ring-0 placeholder:text-foreground-muted/50"
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

type TagChipInputProps = {
  label: string;
  max: number;
  onChange: (value: string[]) => void;
  value: string[];
};

/**
 * Render a chip-based tag editor.
 *
 * Tags commit on Enter or comma, deduplicate, trim, and cap at `max`. Backspace
 * on an empty field removes the last chip. Keeps the parent value as a clean
 * string array so submission matches the backend tag contract directly.
 *
 * @param props - Label, max count, current tags, and change handler.
 */
function TagChipInput({ label, max, onChange, value }: TagChipInputProps) {
  const [draft, setDraft] = useState("");
  const atLimit = value.length >= max;

  /** Commit the trimmed draft as a new tag when there is room and no dupe. */
  function commitDraft(): void {
    const tag = draft.trim();
    setDraft("");
    if (!tag || atLimit || value.includes(tag)) {
      return;
    }
    onChange([...value, tag]);
  }

  function handleKeyDown(event: React.KeyboardEvent<HTMLInputElement>): void {
    if (event.key === "Enter" || event.key === ",") {
      event.preventDefault();
      commitDraft();
      return;
    }
    if (event.key === "Backspace" && draft === "" && value.length > 0) {
      onChange(value.slice(0, -1));
    }
  }

  function handleChange(event: React.ChangeEvent<HTMLInputElement>): void {
    // Typing a comma is treated as a commit separator rather than literal text.
    if (event.target.value.includes(",")) {
      const tag = event.target.value.replace(/,/g, "").trim();
      setDraft("");
      if (tag && !atLimit && !value.includes(tag)) {
        onChange([...value, tag]);
      }
      return;
    }
    setDraft(event.target.value);
  }

  const inputId = "framework-tags";

  return (
    <div className="block">
      <label
        className="mb-1.5 block text-sm font-semibold text-foreground"
        htmlFor={inputId}
      >
        {label}
      </label>
      <div className="flex min-h-12 flex-wrap items-center gap-2 rounded-xl border border-border-default bg-background px-3 py-2 transition-all focus-within:border-accent">
        {value.map((tag) => (
          <span
            key={tag}
            className="inline-flex items-center gap-1 rounded-lg bg-accent/10 py-1 pl-3 pr-1 text-xs font-medium text-foreground"
          >
            {tag}
            <button
              type="button"
              aria-label={`Remove ${tag}`}
              className="flex h-5 w-5 items-center justify-center rounded-md text-foreground-muted transition-colors hover:bg-accent/20 hover:text-foreground"
              onClick={() => onChange(value.filter((current) => current !== tag))}
            >
              <svg
                className="h-3 w-3"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M6 18L18 6M6 6l12 12"
                />
              </svg>
            </button>
          </span>
        ))}
        <input
          id={inputId}
          className="min-w-[8rem] flex-1 bg-transparent text-sm text-foreground outline-none placeholder:text-foreground-muted/50 disabled:cursor-not-allowed"
          disabled={atLimit}
          onBlur={commitDraft}
          onChange={handleChange}
          onKeyDown={handleKeyDown}
          placeholder={
            atLimit ? "Tag limit reached" : "Add a tag, press Enter"
          }
          value={draft}
        />
      </div>
      <span className="mt-1.5 block text-xs text-foreground-muted">
        Up to {max} tags help operators discover your framework. {value.length}/
        {max} used.
      </span>
    </div>
  );
}
