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

type FrameworkFormProps = {
  framework?: FrameworkResponse;
  onSubmit: (payload: FrameworkCreate) => Promise<void>;
  submitLabel?: string;
};

/**
 * Render a Framework create/edit form.
 *
 * @param props - Optional existing Framework and async submit callback.
 */
export function FrameworkForm({
  framework,
  onSubmit,
  submitLabel = "Save framework",
}: FrameworkFormProps) {
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({
    category: framework?.category ?? "operations",
    description: framework?.description ?? "",
    price: framework?.pricing.price ?? "250",
    tags: framework?.tags.join(", ") ?? "",
    title: framework?.title ?? "",
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
        pricing,
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
          className="min-h-32 w-full rounded-xl border border-border-default bg-background px-4 py-3 text-sm text-foreground outline-none transition-all focus:border-accent focus:ring-4 focus:ring-accent/10 placeholder:text-foreground-muted/50 resize-y"
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
        <label className="block">
          <span className="mb-1.5 block text-sm font-semibold text-foreground">
            Category
          </span>
          <div className="relative">
            <select
              className="h-11 w-full appearance-none rounded-xl border border-border-default bg-background pl-4 pr-10 text-sm text-foreground outline-none transition-all focus:border-accent focus:ring-4 focus:ring-accent/10"
              onChange={(event) => setForm((current) => ({ ...current, category: event.target.value }))}
              required
              value={form.category}
            >
              <option value="operations">Operations & Playbooks</option>
              <option value="engineering">Engineering & Architecture</option>
              <option value="design">Design Systems</option>
              <option value="compliance">Compliance & Security</option>
              <option value="finance">Finance & Modeling</option>
              <option value="hr">People & HR</option>
            </select>
            <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center px-3 text-foreground-muted">
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
              </svg>
            </div>
          </div>
        </label>
        
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
              className="h-11 w-full rounded-xl border border-border-default bg-background pl-8 pr-4 text-sm text-foreground outline-none transition-all focus:border-accent focus:ring-4 focus:ring-accent/10 placeholder:text-foreground-muted/50"
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
          className="inline-flex h-11 items-center justify-center rounded-xl bg-foreground px-8 text-sm font-semibold text-background shadow-sm transition hover:bg-foreground/90 disabled:opacity-60 disabled:cursor-not-allowed"
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
        {required && <span className="ml-1 text-accent">*</span>}
      </span>
      <input
        className="h-11 w-full rounded-xl border border-border-default bg-background px-4 text-sm text-foreground outline-none transition-all focus:border-accent focus:ring-4 focus:ring-accent/10 placeholder:text-foreground-muted/50"
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
