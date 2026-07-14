"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { updateOrganizationV1OrgsOrgIdPatch } from "@/lib/generated/sdk.gen";
import type { OrganizationUpdateRequest } from "@/lib/generated/types.gen";
import { getAccessTokenHeaders } from "@/lib/auth/form-client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { useOrganization } from "./organization-context";
import { OrganizationLogoUploader } from "./organization-logo-uploader";
import { useToast } from "@/components/ui/toast";

export function OrganizationProfile() {
  const { orgId, org, role, isSuspended } = useOrganization();
  const router = useRouter();
  const toast = useToast();

  const isAdminOrOwner = role === "admin" || role === "owner";

  const [loading, setLoading] = useState(false);
  // Seed from the loaded org so a fresh upload shows immediately without a
  // full page reload; router.refresh() then re-syncs server-derived data.
  const [logoUrl, setLogoUrl] = useState<string | null>(org.logo_url);

  const [formData, setFormData] = useState<OrganizationUpdateRequest>({
    name: org.name,
    website: org.website,
    description: org.description,
  });

  const isDirty = formData.name !== org.name || formData.website !== org.website || formData.description !== org.description;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!isAdminOrOwner || isSuspended || !isDirty) return;

    setLoading(true);

    try {
      const result = await updateOrganizationV1OrgsOrgIdPatch({
        path: { org_id: orgId },
        body: formData,
        headers: getAccessTokenHeaders(),
      });

      if (!result.response.ok) {
        toast.error(result.error?.detail?.error_code || "Failed to update profile");
      } else {
        toast.success("Profile updated successfully.");
        router.refresh(); // Refresh page data to reflect the changes everywhere
      }
    } catch {
      toast.error("An unexpected error occurred.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="max-w-3xl overflow-hidden rounded-3xl border border-border-default bg-surface-1 shadow-sm transition hover:shadow-bento">
      <div className="border-b border-border-default bg-surface-2/50 px-8 py-6">
        <h2 className="font-heading text-xl font-bold text-foreground tracking-tight">
          Organization Profile
        </h2>
        <p className="mt-1 text-sm text-foreground-muted">
          Manage your organization&apos;s public details.
        </p>
      </div>

      <form onSubmit={handleSubmit} className="flex flex-col gap-6 px-8 py-8">
        <div>
          <span className="mb-1.5 block text-sm font-semibold text-foreground">
            Logo
          </span>
          <OrganizationLogoUploader
            orgId={orgId}
            logoUrl={logoUrl}
            name={org.name}
            canEdit={isAdminOrOwner && !isSuspended}
            onUploaded={(url) => {
              setLogoUrl(url);
              router.refresh();
            }}
          />
        </div>

        <div>
          <label htmlFor="name" className="mb-1.5 block text-sm font-semibold text-foreground">
            Organization Name <span className="text-error">*</span>
          </label>
          <Input
            id="name"
            required
            disabled={!isAdminOrOwner || isSuspended}
            value={formData.name || ""}
            onChange={(e) => setFormData({ ...formData, name: e.target.value })}
            className="rounded-xl bg-background shadow-sm"
          />
        </div>

        <div>
          <label htmlFor="website" className="mb-1.5 block text-sm font-semibold text-foreground">
            Website
          </label>
          <Input
            id="website"
            type="url"
            disabled={!isAdminOrOwner || isSuspended}
            value={formData.website || ""}
            onChange={(e) => setFormData({ ...formData, website: e.target.value })}
            placeholder="https://..."
            className="rounded-xl bg-background shadow-sm"
          />
        </div>

        <div>
          <label htmlFor="description" className="mb-1.5 block text-sm font-semibold text-foreground">
            Description
          </label>
          <Textarea
            id="description"
            disabled={!isAdminOrOwner || isSuspended}
            value={formData.description || ""}
            onChange={(e) => setFormData({ ...formData, description: e.target.value })}
            className="min-h-32 rounded-xl bg-background shadow-sm"
          />
        </div>

        {isAdminOrOwner && (
          <div className="mt-2 flex justify-end border-t border-border-default pt-6">
            <Button type="submit" loading={loading} disabled={isSuspended || !isDirty} className="min-h-12 w-full sm:w-auto rounded-xl shadow-sm">
              Save Changes
            </Button>
          </div>
        )}
      </form>
    </div>
  );
}
