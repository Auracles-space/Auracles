"use client";

/**
 * Become-attestor organization picker.
 *
 * Displays the already-eligible organizations a user can apply with and offers
 * a create-new path when they want to onboard a different organization.
 */
import { useState } from "react";
import { useRouter } from "next/navigation";

import type { AttestorEligibleOrg } from "@/components/modules/organizations/become-attestor";

import { CreateOrganizationDialog } from "./create-organization-dialog";

/**
 * Render the organization chooser for attestor onboarding.
 *
 * @param orgs - Already filtered attestor-eligible organizations.
 */
export function BecomeAttestorPicker({ orgs }: { orgs: AttestorEligibleOrg[] }) {
  const router = useRouter();
  const [isCreateOpen, setIsCreateOpen] = useState(false);

  return (
    <div className="mx-auto w-full max-w-2xl px-4 py-10 md:py-16">
      <header className="mb-8">
        <h1 className="font-heading text-2xl font-bold tracking-tight text-foreground md:text-3xl">
          Choose an organization
        </h1>
        <p className="mt-2 text-sm text-foreground-muted">
          Pick the organization that will apply to become an attestor, or create a new
          one.
        </p>
      </header>

      <ul className="flex flex-col gap-3">
        {orgs.map((org) => (
          <li key={org.id}>
            <button
              type="button"
              onClick={() => router.push(`/dashboard/organizations/${org.id}/attestor`)}
              className="flex min-h-[44px] w-full items-center justify-between gap-4 rounded-2xl border border-border-default bg-surface-1 p-4 text-left transition hover:border-accent/30 hover:shadow-bento"
            >
              <span className="font-heading text-base font-bold text-foreground">
                {org.name}
              </span>
              <span className="rounded-badge bg-surface-2 px-2 py-1 text-xs font-medium text-foreground-muted">
                {org.attestorStatus ? "Resume" : "Not started"}
              </span>
            </button>
          </li>
        ))}
        <li>
          <button
            type="button"
            onClick={() => setIsCreateOpen(true)}
            className="flex min-h-[44px] w-full items-center justify-center rounded-2xl border border-dashed border-border-default bg-surface-1 p-4 text-sm font-semibold text-foreground transition hover:border-accent/30"
          >
            Create a new organization
          </button>
        </li>
      </ul>

      <CreateOrganizationDialog
        open={isCreateOpen}
        onClose={() => setIsCreateOpen(false)}
        redirectIntent="attestor"
      />
    </div>
  );
}
