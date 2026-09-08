"use client";

/**
 * Account completion prompt.
 *
 * Every incomplete-user 403 lands here, whatever the actual blocker was, so the
 * page has to report account state rather than recite a fixed list. It reads
 * `/v1/auth/me` and marks each step done, in review, or outstanding — a user
 * bounced here for a missing role is not told to verify an identity they
 * already verified.
 *
 * A roleless account still sees the role picker alone: a role is the one step
 * that must be settled before the rest of onboarding means anything.
 *
 * Maps to: FR-AUTH-013, FR-AUTH-009.
 */
import Link from "next/link";
import { useEffect, useState } from "react";

import {
  configureBrowserClient,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import { toSafeInternalPath } from "@/lib/auth/onboarding";
import { getCurrentUser } from "@/lib/generated/sdk.gen";

import {
  RoleSelectionForm,
  SELF_ROLES,
  type SelfRole,
} from "./role-selection-form";

/** Completion state of a single onboarding step. */
type StepState = "done" | "in_review" | "todo";

type OnboardingPromptProps = {
  /**
   * The `error_code` the backend returned on the blocked request, forwarded by
   * the incomplete-user interceptor. Decides whether a role the user lacks is
   * treated as outstanding work rather than an optional extra.
   */
  errorCode?: string;
  /**
   * Path the user attempted before being redirected to onboarding. Forwarded
   * to the KYC link as `?next=` so the user can resume their intent once
   * verification completes.
   */
  returnTo?: string;
};

const stateCopy: Record<StepState, { label: string; className: string }> = {
  done: {
    className: "border-success/30 bg-success/10 text-success",
    label: "Done",
  },
  in_review: {
    className: "border-accent/30 bg-accent/10 text-accent",
    label: "In review",
  },
  todo: {
    className: "border-border-strong bg-surface-1 text-foreground-muted",
    label: "To do",
  },
};

/**
 * Render the status pill that reports whether a step still needs the user.
 *
 * @param props - The step's completion state.
 */
function StepStatus({ state }: { state: StepState }) {
  const copy = stateCopy[state];
  return (
    <span
      className={`inline-flex shrink-0 items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold ${copy.className}`}
    >
      {copy.label}
    </span>
  );
}

/**
 * Render one onboarding step as a titled card with its status.
 *
 * @param props - Step copy, completion state, and optional inline action.
 */
function StepCard({
  body,
  children,
  state,
  title,
}: {
  body: string;
  children?: React.ReactNode;
  state: StepState;
  title: string;
}) {
  return (
    <article className="rounded-xl border border-border-default bg-surface-2 p-4">
      <div className="flex items-start justify-between gap-3">
        <h3 className="font-heading text-sm font-semibold text-foreground">
          {title}
        </h3>
        <StepStatus state={state} />
      </div>
      <p className="mt-2 text-sm leading-6 text-foreground-muted">{body}</p>
      {children ? <div className="mt-4">{children}</div> : null}
    </article>
  );
}

/**
 * Render the account completion prompt.
 *
 * @param props - Blocker context from the incomplete-user interceptor.
 */
export function OnboardingPrompt({
  errorCode,
  returnTo,
}: OnboardingPromptProps = {}) {
  const [loaded, setLoaded] = useState(false);
  const [roles, setRoles] = useState<string[]>([]);
  const [pendingRoles, setPendingRoles] = useState<string[]>([]);
  const [profileDone, setProfileDone] = useState(false);
  const [kycStatus, setKycStatus] = useState("unverified");
  // A failed load must not hard-gate the page behind role selection; an
  // unknown account is assumed to have a role rather than pushed into a
  // choice it may already have made.
  const [loadFailed, setLoadFailed] = useState(false);

  useEffect(() => {
    let active = true;

    async function loadUser(): Promise<void> {
      configureBrowserClient();
      try {
        const result = await getCurrentUser({ headers: getAccessTokenHeaders() });
        if (!active) return;
        const user = result.data;
        if (!user) {
          setLoadFailed(true);
          return;
        }
        setRoles(user.roles ?? []);
        setPendingRoles(user.pending_roles ?? []);
        setProfileDone(
          Boolean(user.email_verified) && (user.display_name ?? "").trim().length > 0,
        );
        setKycStatus(user.kyc_status ?? "unverified");
      } catch {
        if (active) setLoadFailed(true);
      } finally {
        if (active) setLoaded(true);
      }
    }

    void loadUser();
    return () => {
      active = false;
    };
  }, []);

  const safeReturnTo = toSafeInternalPath(returnTo);
  const kycHref = safeReturnTo
    ? `/settings/kyc?next=${encodeURIComponent(safeReturnTo)}`
    : "/settings/kyc";

  /** Send the user back to what they were doing, or refresh this page. */
  function resumeAfterRoleChange(): void {
    window.location.assign(safeReturnTo ?? "/settings/onboarding");
  }

  if (!loaded) {
    return null;
  }

  const heldRoles = new Set([...roles, ...pendingRoles]);
  const missingRoles = SELF_ROLES.filter((role) => !heldRoles.has(role));

  // A roleless account gets the picker and nothing else: the remaining steps
  // are meaningless until the account knows what it is for.
  if (!loadFailed && heldRoles.size === 0) {
    return (
      <RoleSelectionForm
        availableRoles={SELF_ROLES}
        description="Pick one or both. You can change this later in settings."
        heading="How will you use Auracles?"
        onSaved={resumeAfterRoleChange}
      />
    );
  }

  const roleBlocked = errorCode === "role_required" && missingRoles.length > 0;
  const profileState: StepState = profileDone ? "done" : "todo";
  const roleState: StepState = roleBlocked ? "todo" : "done";
  const kycState: StepState =
    kycStatus === "verified"
      ? "done"
      : kycStatus === "pending"
        ? "in_review"
        : "todo";

  const primaryAction = !profileDone
    ? { href: "/profile/edit", label: "Complete profile" }
    : kycState === "todo"
      ? { href: kycHref, label: "Verify identity" }
      : { href: safeReturnTo ?? "/dashboard", label: "Continue" };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="font-heading text-xl font-semibold text-foreground">
          Account completion
        </h2>
        <p className="mt-2 text-sm leading-6 text-foreground-muted">
          You can browse and preview frameworks now. Complete these items
          before marketplace actions that require trust checks.
        </p>
      </div>

      <div className="space-y-3">
        <StepCard
          body="Your registered display name is the Phase 1 profile baseline. Expanded public profile fields arrive in the settings phase."
          state={profileState}
          title="Complete your profile"
        />

        <StepCard
          body={
            roleBlocked
              ? "The action you tried is reserved for a role your account does not hold yet. Add it below."
              : "Your account roles decide which marketplace actions are open to you. Add or change them in settings at any time."
          }
          state={roleState}
          title="Choose how you use Auracles"
        >
          {roleBlocked ? (
            <RoleSelectionForm
              availableRoles={missingRoles as SelfRole[]}
              description="Adding a role takes effect immediately — no re-verification needed."
              heading="Add a role"
              onSaved={resumeAfterRoleChange}
              submitLabel="Add role"
            />
          ) : null}
        </StepCard>

        <StepCard
          body={
            kycState === "done"
              ? "Your identity is verified. Nothing further is needed here."
              : kycState === "in_review"
                ? "Your documents are with our team. We will email you when the review is finished."
                : "Upload a photo of a government ID — it takes about a minute. Our team reviews it privately, and your document is never published."
          }
          state={kycState}
          title="Verify your identity"
        />
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <Link
          className="inline-flex min-h-12 w-full items-center justify-center rounded-xl border border-transparent bg-foreground px-4 py-2 text-sm font-semibold text-background transition hover:bg-foreground/90 focus-visible:ring-2 focus-visible:ring-accent active:scale-[0.98]"
          href={primaryAction.href}
        >
          {primaryAction.label}
        </Link>
        <Link
          className="inline-flex min-h-12 w-full items-center justify-center rounded-xl border border-border-default bg-surface-1 px-4 py-2 text-sm font-semibold text-foreground transition hover:bg-surface-2 focus-visible:ring-2 focus-visible:ring-accent"
          href="/explore"
        >
          Browse frameworks
        </Link>
      </div>
    </div>
  );
}
