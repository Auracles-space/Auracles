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

export function OrganizationProfile() {
  const { orgId, org, role, isSuspended } = useOrganization();
  const router = useRouter();

  const isAdminOrOwner = role === "admin" || role === "owner";

  const [loading, setLoading] = useState(false);
  const [success, setSuccess] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [formData, setFormData] = useState<OrganizationUpdateRequest>({
    name: org.name,
    website: org.website,
    description: org.description,
  });

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!isAdminOrOwner || isSuspended) return;

    setLoading(true);
    setError(null);
    setSuccess(false);

    try {
      const result = await updateOrganizationV1OrgsOrgIdPatch({
        path: { org_id: orgId },
        body: formData,
        headers: getAccessTokenHeaders(),
      });

      if (!result.response.ok) {
        setError(result.error?.detail?.error_code || "Failed to update profile");
      } else {
        setSuccess(true);
        router.refresh(); // Refresh page data to reflect the changes everywhere
      }
    } catch {
      setError("An unexpected error occurred.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="max-w-2xl rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
      <h2 className="mb-4 font-heading text-xl font-bold text-foreground">
        Organization Profile
      </h2>

      {error && <p className="mb-4 text-sm text-error">{error}</p>}
      {success && <p className="mb-4 text-sm text-success">Profile updated successfully.</p>}

      <form onSubmit={handleSubmit} className="flex flex-col gap-5">
        <div>
          <label htmlFor="name" className="mb-1 block text-sm font-semibold text-foreground">
            Organization Name
          </label>
          <Input
            id="name"
            required
            disabled={!isAdminOrOwner || isSuspended}
            value={formData.name || ""}
            onChange={(e) => setFormData({ ...formData, name: e.target.value })}
          />
        </div>

        <div>
          <label htmlFor="website" className="mb-1 block text-sm font-semibold text-foreground">
            Website
          </label>
          <Input
            id="website"
            type="url"
            disabled={!isAdminOrOwner || isSuspended}
            value={formData.website || ""}
            onChange={(e) => setFormData({ ...formData, website: e.target.value })}
            placeholder="https://..."
          />
        </div>

        <div>
          <label htmlFor="description" className="mb-1 block text-sm font-semibold text-foreground">
            Description
          </label>
          <Textarea
            id="description"
            disabled={!isAdminOrOwner || isSuspended}
            value={formData.description || ""}
            onChange={(e) => setFormData({ ...formData, description: e.target.value })}
          />
        </div>

        {isAdminOrOwner && (
          <div className="mt-4 flex justify-end">
            <Button type="submit" loading={loading} disabled={isSuspended}>
              Save Changes
            </Button>
          </div>
        )}
      </form>
    </div>
  );
}
