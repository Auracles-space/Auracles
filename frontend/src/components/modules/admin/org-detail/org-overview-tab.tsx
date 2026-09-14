"use client";

/**
 * Overview tab of the admin organization detail page: owners, capabilities
 * with their stored reasons, and member count. Capability changes go through
 * the existing capabilities dialog and patch the overview in place.
 *
 * Maps to: organizations end-to-end design, Slice D (admin org detail).
 */
import { useState } from "react";

import { OrgCapabilitiesDialog } from "@/components/modules/admin/org-capabilities-dialog";
import {
  CAPABILITY_LABELS,
  type OrgCapability,
} from "@/components/modules/admin/org-capability-controls";
import {
  applyCapabilityChange,
  toDirectoryOrg,
} from "@/components/modules/admin/org-detail/org-detail-helpers";
import { EmptyNote, ListRow, Section } from "@/components/modules/admin/org-detail/org-detail-states";
import { Button } from "@/components/ui/button";
import { StatusPill, describeStatus } from "@/components/ui/status-pill";
import type { AdminOrgOverviewResponse } from "@/lib/generated/types.gen";

type OrgOverviewTabProps = {
  /** Organization overview already loaded for the header. */
  org: AdminOrgOverviewResponse;
  /** Replace the overview after a capability change. */
  onChange: (org: AdminOrgOverviewResponse) => void;
};

/**
 * Render the overview tab.
 *
 * @param props - Overview and change handler.
 */
export function OrgOverviewTab({ org, onChange }: OrgOverviewTabProps) {
  const [dialogOpen, setDialogOpen] = useState(false);
  const closed = !!org.deactivated_at;

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Section aside={`${org.member_count} ${org.member_count === 1 ? "member" : "members"}`} title="Owners">
        {org.owners.length === 0 ? (
          <EmptyNote>No owners on record.</EmptyNote>
        ) : (
          <ul className="grid gap-2">
            {org.owners.map((owner) => (
              <ListRow columns="md:grid-cols-2" key={owner.member_id}>
                <p className="break-words font-semibold text-foreground">{owner.display_name}</p>
                <p className="break-all text-sm text-foreground-muted">{owner.email}</p>
              </ListRow>
            ))}
          </ul>
        )}
      </Section>
      <Section
        aside={
          <Button
            className="w-full sm:w-fit"
            disabled={closed}
            onClick={() => setDialogOpen(true)}
            variant="secondary"
          >
            Manage capabilities
          </Button>
        }
        title="Capabilities"
      >
        {org.capabilities.length === 0 ? (
          <EmptyNote>No capabilities activated.</EmptyNote>
        ) : (
          <ul className="grid gap-2">
            {org.capabilities.map((item) => (
              <li className="grid gap-2 rounded-xl border border-border-default bg-surface-2 p-4" key={item.capability}>
                <StatusPill
                  className="w-fit"
                  label={`${CAPABILITY_LABELS[item.capability as OrgCapability] ?? item.capability} ${describeStatus(item.status).label.toLowerCase()}`}
                  status={item.status}
                />
                {item.status_reason ? (
                  <p className="break-words text-sm text-foreground">
                    <span className="font-semibold">Reason:</span> {item.status_reason}
                  </p>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </Section>
      {dialogOpen ? (
        <OrgCapabilitiesDialog
          onChanged={(capability, status, reason) =>
            onChange(applyCapabilityChange(org, capability, status, reason))
          }
          onClose={() => setDialogOpen(false)}
          org={toDirectoryOrg(org)}
        />
      ) : null}
    </div>
  );
}
