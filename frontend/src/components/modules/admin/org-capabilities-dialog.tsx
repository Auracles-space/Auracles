"use client";

/**
 * Admin dialog listing one organization's capabilities with their status,
 * the reason stored on any suspended or revoked one, and the transitions an
 * admin can apply. Contributor and operator capabilities had no admin UI
 * before this; the attestor row uses the same controls as the attestor
 * console so every capability reads and behaves the same way.
 *
 * Maps to: docs/superpowers/specs/2026-09-13-org-onboarding-journey-design.md §2 (Admin console).
 */
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

import {
  CAPABILITY_LABELS,
  OrgCapabilityControls,
  type CapabilityStatusAfter,
  type OrgCapability,
} from "@/components/modules/admin/org-capability-controls";
import { StatusPill } from "@/components/ui/status-pill";
import type { AdminOrgResponse } from "@/lib/generated/types.gen";

const CAPABILITIES: OrgCapability[] = ["contributor", "operator", "attestor"];

type OrgCapabilitiesDialogProps = {
  org: AdminOrgResponse;
  /** Called after a successful transition so the directory row can update. */
  onChanged: (
    capability: OrgCapability,
    status: CapabilityStatusAfter,
    reason: string | null,
  ) => void;
  onClose: () => void;
};

/**
 * Explain a capability state that has no transition buttons.
 *
 * @param status - Capability status, or undefined when never activated.
 */
function describeIdleState(status: string | undefined): string | null {
  if (!status) {
    return "The organization has not activated this capability.";
  }
  if (status === "pending") {
    return "Awaiting activation by the organization.";
  }
  if (status === "revoked") {
    return "Revoked permanently. The organization must activate again from scratch.";
  }
  return null;
}

/**
 * Render the capabilities dialog for one organization.
 *
 * @param props - Organization row, change callback, and close handler.
 */
export function OrgCapabilitiesDialog({ org, onChanged, onClose }: OrgCapabilitiesDialogProps) {
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") {
        onClose();
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  if (typeof document === "undefined") {
    return null;
  }

  return createPortal(
    <div
      aria-labelledby="org-capabilities-title"
      aria-modal="true"
      className="fixed inset-0 z-50 grid place-items-end bg-black/40 p-0 sm:place-items-center sm:p-4"
      onClick={onClose}
      role="dialog"
    >
      <div
        className="max-h-[85vh] w-full overflow-y-auto rounded-t-2xl border border-border-default bg-surface-1 p-6 shadow-sm sm:max-w-lg sm:rounded-2xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
              Capabilities
            </p>
            <h2
              className="mt-1 font-heading text-xl font-bold text-foreground"
              id="org-capabilities-title"
            >
              {org.name}
            </h2>
            <p className="mt-1 text-xs text-foreground-muted">@{org.slug}</p>
          </div>
          <button
            className="min-h-11 rounded-xl px-3 text-sm font-semibold text-foreground-muted hover:text-foreground"
            onClick={onClose}
            type="button"
          >
            Close
          </button>
        </div>

        <p className="mt-3 text-sm text-foreground-muted">
          Suspending or revoking removes the matching role from every member.
          Reasons are shown to the organization&apos;s owner.
        </p>

        {error ? <p className="mt-3 text-sm text-error">{error}</p> : null}

        <div className="mt-4 grid gap-3">
          {CAPABILITIES.map((capability) => {
            const status = org.capabilities[capability];
            const reason = org.capability_reasons?.[capability];
            const idle = describeIdleState(status);
            return (
              <section
                className="rounded-xl border border-border-default bg-surface-2 p-4"
                key={capability}
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <h3 className="font-heading text-base font-bold text-foreground">
                    {CAPABILITY_LABELS[capability]}
                  </h3>
                  <StatusPill status={status ?? "inactive"} />
                </div>
                {reason ? (
                  <p className="mt-2 text-sm text-foreground">
                    <span className="font-semibold">Reason:</span> {reason}
                  </p>
                ) : null}
                {idle ? (
                  <p className="mt-2 text-sm text-foreground-muted">{idle}</p>
                ) : (
                  <div className="mt-3">
                    <OrgCapabilityControls
                      capability={capability}
                      onChanged={(next, sentReason) => {
                        setError(null);
                        onChanged(capability, next, sentReason);
                      }}
                      onError={setError}
                      orgId={org.id}
                      orgName={org.name}
                      status={status ?? ""}
                    />
                  </div>
                )}
              </section>
            );
          })}
        </div>
      </div>
    </div>,
    document.body,
  );
}
