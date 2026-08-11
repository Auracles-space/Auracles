"use client";

/**
 * First-time role selection for accounts that arrive without a role.
 *
 * Google sign-up skips the registration form's role picker, so a brand-new
 * Google user lands here roleless. This step assigns Contributor and/or Operator
 * via the self-service role endpoint. Attestor is intentionally absent: it needs
 * admin approval and is requested through registration, not self-onboarding.
 *
 * The step self-hides for users who already hold a role, so it is safe to render
 * unconditionally inside the onboarding page.
 */
import { useEffect, useState, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import { addRoleV1AuthRolesPost, getCurrentUser } from "@/lib/generated/sdk.gen";

import { FormMessage } from "./form-message";

type SelfRole = "contributor" | "operator";

const roleOptions: Array<{ description: string; label: string; value: SelfRole }> = [
  {
    description: "Package professional expertise into licensed frameworks.",
    label: "Contributor",
    value: "contributor",
  },
  {
    description: "Purchase frameworks and manage implementation work.",
    label: "Operator",
    value: "operator",
  },
];

type OnboardingRoleStepProps = {
  /** The rest of onboarding, shown only once the user has a role. */
  children?: ReactNode;
};

/**
 * Gate onboarding on role selection.
 *
 * Fetches the current roles on mount. A roleless user sees only the role
 * picker; once a role is saved (or for users who already have one) the
 * remaining onboarding steps (`children`) are shown instead. This makes role
 * selection a hard first step rather than a skippable section.
 *
 * @param props - The downstream onboarding steps to gate behind a role.
 */
export function OnboardingRoleStep({ children }: OnboardingRoleStepProps) {
  const [loaded, setLoaded] = useState(false);
  const [hasRole, setHasRole] = useState(true);
  const [roles, setRoles] = useState<SelfRole[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);

  useEffect(() => {
    let active = true;
    async function loadRoles(): Promise<void> {
      configureBrowserClient();
      try {
        const result = await getCurrentUser({ headers: getAccessTokenHeaders() });
        if (!active) return;
        const current = result.data?.roles ?? [];
        const pending = result.data?.pending_roles ?? [];
        setHasRole(current.length > 0 || pending.length > 0);
      } catch {
        // On failure, keep the step hidden rather than block onboarding.
        if (!active) return;
        setHasRole(true);
      } finally {
        if (active) setLoaded(true);
      }
    }
    void loadRoles();
    return () => {
      active = false;
    };
  }, []);

  function toggleRole(role: SelfRole): void {
    setRoles((current) =>
      current.includes(role)
        ? current.filter((value) => value !== role)
        : [...current, role],
    );
    if (error) setError(null);
  }

  async function saveRoles(): Promise<void> {
    if (roles.length === 0) {
      setError("Pick at least one way to use Auracles.");
      return;
    }
    setIsSaving(true);
    setError(null);
    configureBrowserClient();
    for (const role of roles) {
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
    // A fresh load reflects the new role across the onboarding gate and nav.
    window.location.reload();
  }

  if (!loaded) {
    return null;
  }
  if (hasRole) {
    return <>{children}</>;
  }

  return (
    <section className="space-y-4">
      <div>
        <h2 className="font-heading text-xl font-semibold text-foreground">
          How will you use Auracles?
        </h2>
        <p className="mt-2 text-sm leading-6 text-foreground-muted">
          Pick one or both. You can change this later in settings.
        </p>
      </div>

      {error ? <FormMessage kind="error" message={error} /> : null}

      <div className="space-y-3">
        {roleOptions.map((role) => {
          const isSelected = roles.includes(role.value);
          return (
            <label
              className={`flex min-h-12 cursor-pointer gap-3 rounded-xl border p-4 transition ${
                isSelected
                  ? "border-accent bg-surface-1"
                  : "border-border-strong bg-surface-2 hover:border-accent/40"
              }`}
              htmlFor={`onboarding-role-${role.value}`}
              key={role.value}
            >
              <input
                checked={isSelected}
                className="mt-1 h-4 w-4 accent-accent"
                id={`onboarding-role-${role.value}`}
                onChange={() => toggleRole(role.value)}
                type="checkbox"
              />
              <span>
                <span className="block text-sm font-semibold text-foreground">
                  {role.label}
                </span>
                <span className="mt-1 block text-xs leading-5 text-foreground-muted">
                  {role.description}
                </span>
              </span>
            </label>
          );
        })}
      </div>

      <Button
        className="w-full sm:w-auto"
        disabled={isSaving || roles.length === 0}
        loading={isSaving}
        onClick={saveRoles}
        type="button"
      >
        {isSaving ? "Saving" : "Save and continue"}
      </Button>
    </section>
  );
}
