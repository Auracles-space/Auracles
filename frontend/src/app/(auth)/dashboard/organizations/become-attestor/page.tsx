"use client";

/**
 * Become-attestor front-door entry page.
 *
 * Loads the current user's organizations, resolves the attestor onboarding
 * path, and either redirects directly, shows the eligible-org picker, or opens
 * organization creation with attestor intent.
 */
import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import {
  resolveAttestorEntry,
  type AttestorEntryResolution,
} from "@/components/modules/organizations/become-attestor";
import { BecomeAttestorPicker } from "@/components/modules/organizations/become-attestor-picker";
import { CreateOrganizationDialog } from "@/components/modules/organizations/create-organization-dialog";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import {
  configureBrowserClient,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import { listMyOrganizationsV1OrgsMineGet } from "@/lib/generated/sdk.gen";

/**
 * Resolve how the current user should enter org attestor onboarding.
 */
export default function BecomeAttestorPage() {
  const router = useRouter();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [resolution, setResolution] = useState<AttestorEntryResolution | null>(null);

  const loadOrganizations = useCallback(async () => {
    setLoading(true);
    setError(null);
    configureBrowserClient();

    try {
      const result = await listMyOrganizationsV1OrgsMineGet({
        headers: getAccessTokenHeaders(),
      });

      if (!result.response.ok || !result.data) {
        setError("We couldn't load your organizations.");
        setLoading(false);
        return;
      }

      const nextResolution = resolveAttestorEntry(result.data.organizations);
      if (nextResolution.kind === "direct") {
        router.replace(`/dashboard/organizations/${nextResolution.orgId}/attestor`);
        return;
      }

      setResolution(nextResolution);
      setLoading(false);
    } catch {
      setError("Something went wrong loading your organizations.");
      setLoading(false);
    }
  }, [router]);

  useEffect(() => {
    void loadOrganizations();
  }, [loadOrganizations]);

  if (loading) {
    return (
      <div className="flex justify-center py-20">
        <Spinner className="h-8 w-8 text-accent" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="mx-auto w-full max-w-2xl px-4 py-16">
        <div className="rounded-2xl border border-error/50 bg-error/5 p-6 text-center">
          <p className="text-error">{error}</p>
          <Button className="mt-4" variant="secondary" onClick={() => void loadOrganizations()}>
            Retry
          </Button>
        </div>
      </div>
    );
  }

  if (resolution?.kind === "picker") {
    return <BecomeAttestorPicker orgs={resolution.orgs} />;
  }

  return (
    <CreateOrganizationDialog
      open
      onClose={() => router.push("/dashboard/organizations")}
      redirectIntent="attestor"
    />
  );
}
