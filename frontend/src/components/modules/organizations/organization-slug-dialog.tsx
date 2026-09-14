"use client";

/**
 * Owner-only dialog for changing an organization's public address (slug).
 *
 * Applies the same slug rules as creation, previews the new public URL, and
 * warns that the old link keeps working by redirecting. The PATCH is gated by
 * step-up 2FA server-side; the global step-up interceptor installed by
 * `configureBrowserClient()` prompts and replays, so no per-form 2FA wiring.
 * Bottom sheet on phones, centred card from `sm:` (via `ConfirmDialog`).
 *
 * Maps to: docs/superpowers/specs/2026-09-14-organizations-end-to-end-design.md
 * Decision 5, §Slug change.
 */
import { useEffect, useId, useState } from "react";

import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { useToast } from "@/components/ui/toast";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import { changeOrgSlugV1OrgsOrgIdSlugPatch } from "@/lib/generated/sdk.gen";

import { useOrganization } from "./organization-context";

/** Creation-time slug rule: lowercase letters, digits, hyphens; 3–80 chars. */
const SLUG_PATTERN = /^[a-z0-9-]{3,80}$/;

type OrganizationSlugDialogProps = {
  /** Whether the dialog is visible. */
  open: boolean;
  /** Called when the dialog is dismissed or the change succeeds. */
  onClose: () => void;
};

/**
 * Render the slug change dialog for the organization in context.
 *
 * @param props - Open state and close callback.
 */
export function OrganizationSlugDialog({ open, onClose }: OrganizationSlugDialogProps) {
  const { orgId, org, refreshOrganization } = useOrganization();
  const toast = useToast();
  const inputId = useId();
  const [slug, setSlug] = useState(org.slug);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // window is only available after mount; the preview falls back to the path.
  const [origin, setOrigin] = useState("");
  useEffect(() => setOrigin(window.location.origin), []);

  const valid = SLUG_PATTERN.test(slug) && slug !== org.slug;

  async function submit(): Promise<void> {
    if (!valid || busy) return;
    setBusy(true);
    setError(null);
    configureBrowserClient();
    const result = await changeOrgSlugV1OrgsOrgIdSlugPatch({
      body: { slug },
      headers: getAccessTokenHeaders(),
      path: { org_id: orgId },
    });
    if (!result.response.ok) {
      // 409 (taken now or in history) and 429 carry server wording; both
      // are about this one field, so the message sits under it.
      setError(describeGeneratedError(result.error));
      setBusy(false);
      return;
    }
    setBusy(false);
    onClose();
    await refreshOrganization();
    toast.success("Public address updated.");
  }

  return (
    <ConfirmDialog
      busy={busy}
      confirmDisabled={!valid}
      confirmLabel="Change address"
      description={
        <div className="grid gap-3">
          <p>Your current link /orgs/{org.slug} will keep working and redirect here.</p>
          <div className="grid gap-1.5">
            <label className="text-sm font-semibold text-foreground" htmlFor={inputId}>
              New address
            </label>
            <input
              aria-describedby={`${inputId}-rule`}
              aria-invalid={error ? true : undefined}
              autoComplete="off"
              className="min-h-11 rounded-xl border border-border-default bg-background px-3 text-sm text-foreground outline-none focus-visible:ring-2 focus-visible:ring-accent"
              id={inputId}
              onChange={(event) => {
                setSlug(event.target.value.toLowerCase());
                setError(null);
              }}
              value={slug}
            />
            <p className="text-xs text-foreground-muted" id={`${inputId}-rule`}>
              Lowercase letters, numbers, and hyphens; 3–80 characters.
            </p>
            {error ? <p className="text-sm text-error">{error}</p> : null}
          </div>
          <code
            className="break-all rounded-xl border border-border-default bg-surface-2 px-3 py-2 text-xs text-foreground"
            data-testid="slug-preview"
          >
            {origin}/orgs/{slug}
          </code>
        </div>
      }
      eyebrow="Public profile"
      onClose={onClose}
      onConfirm={() => void submit()}
      open={open}
      title="Change public address"
    />
  );
}
