"use client";

import { useEffect, useId, useState } from "react";
import { createPortal } from "react-dom";
import { useRouter } from "next/navigation";
import { createOrganizationV1OrgsPost } from "@/lib/generated/sdk.gen";
import type { OrganizationCreateRequest } from "@/lib/generated/types.gen";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Select } from "@/components/ui/select";
import { STRIPE_CONNECT_COUNTRIES } from "@/lib/marketplace/countries";
import { getAccessTokenHeaders } from "@/lib/auth/form-client";

type CreateOrganizationDialogProps = {
  open: boolean;
  onClose: () => void;
  /** When set, successful creation redirects into that onboarding flow. */
  redirectIntent?: "attestor";
};


export function CreateOrganizationDialog({
  open,
  onClose,
  redirectIntent,
}: CreateOrganizationDialogProps) {
  const router = useRouter();
  const titleId = useId();

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [slugError, setSlugError] = useState<string | null>(null);

  const [formData, setFormData] = useState<OrganizationCreateRequest>({
    slug: "",
    name: "",
    country: "US",
    website: "",
    description: "",
  });

  // Portal to <body> so the modal escapes the app-shell <main> stacking
  // context (relative z-20) and can cover the sticky header (z-30). Mount gate
  // keeps createPortal off the server render.
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  if (!open || !mounted) return null;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    setSlugError(null);

    // Client side slug validation
    if (!/^[a-z0-9-]+$/.test(formData.slug)) {
      setSlugError("Slug must be lowercase letters, numbers, and hyphens only.");
      setLoading(false);
      return;
    }

    try {
      const result = await createOrganizationV1OrgsPost({
        body: formData,
        headers: getAccessTokenHeaders(),
      });

      if (!result.response.ok) {
        if (result.response.status === 409) {
          setSlugError("This slug is already taken.");
        } else if (result.response.status === 422) {
           setError("Please check your input values.");
        } else {
          setError(result.error?.detail?.error_code || "Failed to create organization");
        }
        setLoading(false);
        return;
      }

      const orgId = result.data?.id;
      router.push(
        redirectIntent === "attestor"
          ? `/dashboard/organizations/${orgId}/attestor`
          : `/dashboard/organizations/${orgId}`,
      );
    } catch {
      setError("An unexpected error occurred.");
      setLoading(false);
    }
  }

  return createPortal(
    <div
      aria-labelledby={titleId}
      aria-modal="true"
      className="fixed inset-0 z-50 grid place-items-end bg-black/40 p-0 motion-safe:animate-[fade-in_120ms_ease-out] sm:place-items-center sm:p-4"
      onClick={onClose}
      role="dialog"
    >
      <div
        className="w-full rounded-t-2xl border border-border-default bg-surface-1 p-5 shadow-xl sm:max-w-md sm:rounded-2xl"
        onClick={(event) => event.stopPropagation()}
      >
        <h2
          className={`font-heading text-xl font-bold text-foreground ${
            redirectIntent === "attestor" ? "" : "mb-4"
          }`}
          id={titleId}
        >
          {redirectIntent === "attestor"
            ? "Create your attesting organization"
            : "Create Organization"}
        </h2>
        {redirectIntent === "attestor" && (
          <p className="mb-4 mt-1 text-sm text-foreground-muted">
            Next, you&apos;ll complete the attestor application to get verified.
          </p>
        )}

        {error && <p className="mb-4 text-sm text-error">{error}</p>}

        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <div>
            <label htmlFor="name" className="mb-1 block text-sm font-semibold text-foreground">
              Organization Name <span className="text-error">*</span>
            </label>
            <Input
              id="name"
              required
              value={formData.name}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              placeholder="Acme Corp"
            />
          </div>

          <div>
            <label htmlFor="slug" className="mb-1 block text-sm font-semibold text-foreground">
              Slug <span className="text-error">*</span>
            </label>
            <Input
              id="slug"
              required
              value={formData.slug}
              onChange={(e) => setFormData({ ...formData, slug: e.target.value.toLowerCase() })}
              placeholder="acme-corp"
            />
            {slugError && <p className="mt-1 text-sm text-error">{slugError}</p>}
            <p className="mt-1 text-xs text-foreground-muted">
              Used in URLs. Lowercase, numbers, hyphens only.
            </p>
          </div>

          <div>
            <label htmlFor="country" className="mb-1 block text-sm font-semibold text-foreground">
              Country <span className="text-error">*</span>
            </label>
            <Select
              id="country"
              required
              value={formData.country}
              onChange={(e) => setFormData({ ...formData, country: e.target.value })}
            >
              {STRIPE_CONNECT_COUNTRIES.map((c) => (
                <option key={c.code} value={c.code}>
                  {c.name}
                </option>
              ))}
            </Select>
          </div>

          <div>
            <label htmlFor="website" className="mb-1 block text-sm font-semibold text-foreground">
              Website
            </label>
            <Input
              id="website"
              type="url"
              value={formData.website || ""}
              onChange={(e) => setFormData({ ...formData, website: e.target.value })}
              placeholder="https://acme.com"
            />
          </div>

          <div>
            <label htmlFor="description" className="mb-1 block text-sm font-semibold text-foreground">
              Description
            </label>
            <Textarea
              id="description"
              value={formData.description || ""}
              onChange={(e) => setFormData({ ...formData, description: e.target.value })}
              placeholder="A brief description of your organization."
            />
          </div>

          <div className="mt-2 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <Button variant="secondary" onClick={onClose} disabled={loading}>
              Cancel
            </Button>
            <Button type="submit" loading={loading}>
              {redirectIntent === "attestor" ? "Create & continue" : "Create Organization"}
            </Button>
          </div>
        </form>
      </div>
    </div>,
    document.body,
  );
}
