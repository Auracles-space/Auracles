"use client";

/**
 * Org Operator licensed Framework library.
 *
 * Lists the organization's licenses and requests short-lived download URLs for
 * artifacts using the org operator capability. An "Active" / "All" control
 * passes `include_inactive` so expired and revoked licenses can be reviewed
 * too; those read as such through `StatusPill` and offer no download.
 */
import { useEffect, useState } from "react";

import { listOrgLibrary } from "@/lib/generated/sdk.gen";
import type { LibraryItem } from "@/lib/generated/types.gen";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import { CardSkeleton } from "@/components/ui/skeletons/card-skeleton";
import { SegmentedControl, type SegmentOption } from "@/components/ui/segmented-control";
import { useOrganization } from "@/components/modules/organizations/organization-context";

import { LibraryCard } from "./org-library-card";

type LicenseScope = "active" | "all";

const SCOPE_OPTIONS: SegmentOption<LicenseScope>[] = [
  { value: "active", label: "Active" },
  { value: "all", label: "All" },
];

type OrgOperatorLibraryProps = {
  orgId: string;
};

/**
 * Render Org Operator licenses and download actions.
 *
 * @param props.orgId - Organization whose shared library is listed.
 */
export function OrgOperatorLibrary({ orgId }: OrgOperatorLibraryProps) {
  const { role } = useOrganization();
  const canManage = role === "admin" || role === "owner";
  const [scope, setScope] = useState<LicenseScope>("active");
  const [error, setError] = useState<string | null>(null);
  const [items, setItems] = useState<LibraryItem[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function loadLibrary() {
      setLoading(true);
      setError(null);
      configureBrowserClient();
      const result = await listOrgLibrary({
        headers: getAccessTokenHeaders(),
        path: { org_id: orgId },
        query: { include_inactive: scope === "all" },
      });
      if (!result.response.ok || !result.data) {
        setError(describeGeneratedError(result.error));
        setLoading(false);
        return;
      }
      setItems(result.data.items);
      setLoading(false);
    }

    void loadLibrary();
  }, [orgId, scope]);

  return (
    <div className="grid gap-4">
      <SegmentedControl
        className="sm:max-w-xs"
        label="Filter licenses by status"
        onChange={setScope}
        options={SCOPE_OPTIONS}
        value={scope}
      />
      <LibraryResults canManage={canManage} error={error} items={items} loading={loading} orgId={orgId} />
    </div>
  );
}

type LibraryResultsProps = {
  canManage: boolean;
  error: string | null;
  items: LibraryItem[];
  loading: boolean;
  orgId: string;
};

/** Render the loading, error, empty, or populated state of the library list. */
function LibraryResults({ canManage, error, items, loading, orgId }: LibraryResultsProps) {
  if (loading) {
    return <CardSkeleton />;
  }

  if (error) {
    return <p className="text-sm text-error">{error}</p>;
  }

  if (items.length === 0) {
    return (
      <div className="rounded-2xl border border-border-default bg-surface-2 p-8 text-center shadow-sm">
        <h2 className="font-heading text-xl font-bold text-foreground">
          No licensed frameworks yet
        </h2>
        <p className="mt-2 text-sm text-foreground-muted">
          Purchased frameworks for this organization will appear here.
        </p>
      </div>
    );
  }

  return (
    <>
      {items.map((item) => (
        <LibraryCard
          canManage={canManage}
          item={item}
          orgId={orgId}
          key={item.license_id}
        />
      ))}
    </>
  );
}
