"use client";

/**
 * Become-attestor organization picker.
 *
 * Displays the organizations a user could apply with and offers a create-new
 * path. An org still in business verification is listed but not clickable,
 * with a link to the verification page that unblocks it.
 */
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import type { AttestorEligibleOrg } from "@/components/modules/organizations/become-attestor";

import { CreateOrganizationDialog } from "./create-organization-dialog";

/**
 * Render the organization chooser for attestor onboarding.
 *
 * @param orgs - Owner/admin organizations without an active attestor capability.
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
            {!org.eligible ? (
              <div className="flex min-h-[44px] w-full flex-col gap-2 rounded-2xl border border-dashed border-border-default bg-surface-1 p-4 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <p className="font-heading text-base font-bold text-foreground">{org.name}</p>
                  <p className="mt-1 text-sm text-foreground-muted">
                    Verify the business first. Attestor applications open once
                    verification is approved.
                  </p>
                </div>
                <Link
                  className="inline-flex min-h-11 shrink-0 items-center justify-center rounded-xl border border-border-default bg-surface-2 px-4 text-sm font-semibold text-foreground transition hover:bg-surface-3"
                  href={`/dashboard/organizations/${org.id}/verification`}
                >
                  Go to verification
                </Link>
              </div>
            ) : (
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
            )}
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
