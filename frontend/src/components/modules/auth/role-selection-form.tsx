"use client";

/**
 * Shared picker for the self-assignable Auracles roles.
 *
 * Contributor and Operator are the two roles a user may grant themselves;
 * Attestor is issued through an organization and is deliberately absent. This
 * component is the single write path for `POST /v1/auth/roles`, used both by
 * first-run onboarding (where a role is mandatory) and by settings (where a
 * second role is added later).
 *
 * Maps to: FR-AUTH-013.
 */
import { useId, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import { refreshAccessToken } from "@/lib/auth/refresh-client";
import { addRoleV1AuthRolesPost } from "@/lib/generated/sdk.gen";

import { FormMessage } from "./form-message";

/** A role a user is allowed to grant themselves. */
export type SelfRole = "contributor" | "operator";

/** The self-assignable roles, in the order they are offered. */
export const SELF_ROLES: SelfRole[] = ["contributor", "operator"];

const roleCopy: Record<SelfRole, { description: string; label: string }> = {
  contributor: {
    description: "Package professional expertise into licensed frameworks.",
    label: "Contributor",
  },
  operator: {
    description: "Purchase frameworks and manage implementation work.",
    label: "Operator",
  },
};

/**
 * Return the human label for a role identifier.
 *
 * @param role - Raw role string from `/v1/auth/me`.
 */
export function describeRole(role: string): string {
  if (role in roleCopy) {
    return roleCopy[role as SelfRole].label;
  }
  return role.charAt(0).toUpperCase() + role.slice(1);
}

type RoleSelectionFormProps = {
  /** Roles to offer — callers pass only what the user does not already hold. */
  availableRoles: SelfRole[];
  /** Sentence explaining the consequence of the choice. */
  description: string;
  /** Section heading. */
  heading: string;
  /** Label for the submit control. */
  submitLabel?: string;
  /** Called once every selected role is assigned and the token is reissued. */
  onSaved: () => void | Promise<void>;
};

/**
 * Render the self-assignable role picker.
 *
 * Assigns each selected role in turn, then reissues the access token before
 * handing control back. The reissue is not optional: `require_role` reads the
 * role claims out of the JWT rather than the database, so a freshly added role
 * is inert until a new token is minted and the action the user just unlocked
 * would still return 403. `/v1/auth/refresh` re-reads roles from the database
 * and rewrites the signed `session_hint` cookie alongside the token, so one
 * call settles both the API gate and the middleware route guard.
 *
 * @param props - Roles to offer, surrounding copy, and the success callback.
 */
export function RoleSelectionForm({
  availableRoles,
  description,
  heading,
  submitLabel = "Save and continue",
  onSaved,
}: RoleSelectionFormProps) {
  const fieldPrefix = useId();
  const [selected, setSelected] = useState<SelfRole[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);

  function toggleRole(role: SelfRole): void {
    setSelected((current) =>
      current.includes(role)
        ? current.filter((value) => value !== role)
        : [...current, role],
    );
    if (error) setError(null);
  }

  async function saveRoles(): Promise<void> {
    if (selected.length === 0) {
      setError("Pick at least one way to use Auracles.");
      return;
    }

    setIsSaving(true);
    setError(null);
    configureBrowserClient();
    for (const role of selected) {
      const result = await addRoleV1AuthRolesPost({
        body: { role },
        headers: getAccessTokenHeaders(),
      });
      if (!result.response.ok) {
        setIsSaving(false);
        setError(describeGeneratedError(result.error));
        return;
      }
    }

    await refreshAccessToken();
    await onSaved();
  }

  return (
    <div className="space-y-4">
      <div>
        <h2 className="font-heading text-xl font-semibold text-foreground">
          {heading}
        </h2>
        <p className="mt-2 text-sm leading-6 text-foreground-muted">
          {description}
        </p>
      </div>

      {error ? <FormMessage kind="error" message={error} /> : null}

      <div className="space-y-3">
        {availableRoles.map((role) => {
          const isSelected = selected.includes(role);
          const fieldId = `${fieldPrefix}-${role}`;
          return (
            <label
              className={`flex min-h-12 cursor-pointer gap-3 rounded-xl border p-4 transition ${
                isSelected
                  ? "border-accent bg-surface-1"
                  : "border-border-strong bg-surface-2 hover:border-accent/40"
              }`}
              htmlFor={fieldId}
              key={role}
            >
              <input
                checked={isSelected}
                className="mt-1 h-4 w-4 accent-accent"
                id={fieldId}
                onChange={() => toggleRole(role)}
                type="checkbox"
              />
              <span>
                <span className="block text-sm font-semibold text-foreground">
                  {roleCopy[role].label}
                </span>
                <span className="mt-1 block text-xs leading-5 text-foreground-muted">
                  {roleCopy[role].description}
                </span>
              </span>
            </label>
          );
        })}
      </div>

      <Button
        className="w-full sm:w-auto"
        disabled={isSaving}
        loading={isSaving}
        onClick={() => void saveRoles()}
        type="button"
      >
        {isSaving ? "Saving" : submitLabel}
      </Button>
    </div>
  );
}
