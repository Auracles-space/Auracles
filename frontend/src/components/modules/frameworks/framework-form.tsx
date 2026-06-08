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
    <form className="grid gap-4" onSubmit={handleSubmit}>
      <FormTextInput
        label="Title"
        onChange={(value) => setForm((current) => ({ ...current, title: value }))}
        required
        value={form.title}
      />
      <label className="block">
        <span className="mb-2 block text-sm font-semibold text-foreground">
          Description
        </span>
        <textarea
          className="min-h-32 w-full rounded-[6px] border border-border-default bg-surface-2 px-3 py-2 text-sm text-foreground outline-none focus:border-accent"
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
      <div className="grid gap-4 sm:grid-cols-2">
        <FormTextInput
          label="Category"
          onChange={(value) =>
            setForm((current) => ({ ...current, category: value }))
          }
          required
          value={form.category}
        />
        <FormTextInput
          label="Price"
          onChange={(value) =>
            setForm((current) => ({ ...current, price: value }))
          }
          required
          value={form.price}
        />
      </div>
      <FormTextInput
        label="Tags"
        onChange={(value) => setForm((current) => ({ ...current, tags: value }))}
        value={form.tags}
      />
      {error ? <p className="text-sm text-error">{error}</p> : null}
      <button
        className="inline-flex min-h-11 items-center justify-center rounded-[6px] bg-foreground px-4 py-2 text-sm font-semibold text-background transition hover:bg-foreground/90 disabled:opacity-60"
        disabled={saving}
        type="submit"
      >
        {saving ? "Saving" : submitLabel}
      </button>
    </form>
  );
}

type FormTextInputProps = {
  label: string;
  onChange: (value: string) => void;
  required?: boolean;
  value: string;
};

/**
 * Render one Brand Book text input.
 *
 * @param props - Label, value, and change handler.
 */
function FormTextInput({
  label,
  onChange,
  required = false,
  value,
}: FormTextInputProps) {
  return (
    <label className="block">
      <span className="mb-2 block text-sm font-semibold text-foreground">
        {label}
      </span>
      <input
        className="min-h-11 w-full rounded-[6px] border border-border-default bg-surface-2 px-3 text-sm text-foreground outline-none focus:border-accent"
        onChange={(event) => onChange(event.target.value)}
        required={required}
        value={value}
      />
    </label>
  );
}
