"use client";

/**
 * Review queue for one attestor organization.
 *
 * Splits the org's attestations into the reviews still owed work and the ones
 * already finished, and puts the completion deadline on every active card so a
 * slipping review is visible before the requestor chases it. Cards stack on
 * mobile — this is never a table.
 *
 * Maps to: docs/superpowers/specs/2026-09-14-attestation-request-to-report-design.md §2
 * (Attestor org).
 */

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";

import { useOrganization } from "@/components/modules/organizations/organization-context";
import { listOrgAttestationsV1OrgsOrgIdAttestationsGet } from "@/lib/generated/sdk.gen";
import { getAccessTokenHeaders, describeGeneratedError } from "@/lib/auth/form-client";
import { OrgAttestationItem } from "@/lib/generated/types.gen";
import { Spinner } from "@/components/ui/spinner";
import { Tabs, tabPanelId, tabId } from "@/components/ui/tabs";
import { QueueCard } from "./queue-card";
import { ReassignReviewerDialog } from "./reassign-reviewer-dialog";

// "Active" = the review still needs reviewer/org action. Once the report is
// submitted the reviewer's work is done (it moves to History), so this is a
// narrower set than the backend's _IN_FLIGHT_REVIEW_STATUSES, which counts
// report_submitted as still in flight for the org-level nav badge.
const ACTIVE_QUEUE_STATUSES = [
  "accepted",
  "in_review",
  "revision_requested",
  "disputed",
];

// History tab — reviews the reviewer has submitted plus terminal outcomes.
// `closed` is the legacy settled status; `released` and `refunded` are what
// the backend writes now, and `cancelled` is a requestor withdrawal.
const COMPLETED_QUEUE_STATUSES = [
  "report_submitted",
  "released",
  "resolved",
  "refunded",
  "closed",
  "cancelled",
];

export function AttestationQueueTab() {
  const router = useRouter();
  const { orgId, role } = useOrganization();
  const [attestations, setAttestations] = useState<OrgAttestationItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<"active" | "history">("active");

  const [reassigningId, setReassigningId] = useState<string | null>(null);

  async function load(isMounted: () => boolean) {
    setLoading(true);
    setError(null);
    const res = await listOrgAttestationsV1OrgsOrgIdAttestationsGet({
      path: { org_id: orgId! },
      headers: getAccessTokenHeaders(),
    });
    if (!isMounted()) return;
    setLoading(false);
    if (res.error) {
      setError(describeGeneratedError(res.error));
    } else if (res.data) {
      setAttestations(res.data.attestations);
    }
  }

  useEffect(() => {
    let mounted = true;
    if (!orgId) return;

    const doLoad = async () => {
      setLoading(true);
      await load(() => mounted);
      if (mounted) setLoading(false);
    };
    doLoad();
    return () => { mounted = false; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orgId]);

  if (loading) {
    return <div className="p-4 flex items-center gap-2 text-sm text-foreground-muted"><Spinner className="w-4 h-4" /> Loading queue...</div>;
  }

  if (error) {
    return <div className="p-4 text-sm text-error bg-error/5 border border-error/20 rounded-md">{error}</div>;
  }

  const isAdmin = role === "admin" || role === "owner";
  const activeAttestations = attestations.filter((a) =>
    ACTIVE_QUEUE_STATUSES.includes(a.status),
  );
  const completedAttestations = attestations.filter((a) =>
    COMPLETED_QUEUE_STATUSES.includes(a.status),
  );
  const hasUnreadAnswer = activeAttestations.some((a) => a.unread_answer);

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <h2 className="text-xl font-semibold tracking-tight text-foreground">Attestation queue</h2>
      </div>

      <Tabs
        label="Attestation views"
        activeId={activeTab}
        onChange={(id) => setActiveTab(id as "active" | "history")}
        tabs={[
          {
            id: "active",
            label: "Active",
            count: activeAttestations.length,
            dot: hasUnreadAnswer,
            dotLabel: "Clarification answer awaiting review",
          },
          { id: "history", label: "History", count: completedAttestations.length },
        ]}
      />

      {activeTab === "active" ? (
        <div id={tabPanelId("active")} role="tabpanel" aria-labelledby={tabId("active")}>
          {activeAttestations.length === 0 ? (
            <div className="p-8 text-center text-foreground-muted border border-border-default border-dashed rounded-xl bg-surface-2">
              <h3 className="font-semibold text-foreground mb-1">Queue empty</h3>
              <p className="text-sm">There are no active attestations in your queue.</p>
            </div>
          ) : (
            <div className="grid gap-4">
              {activeAttestations.map((att) => (
                <QueueCard
                  active
                  attestation={att}
                  isAdmin={isAdmin}
                  key={att.id}
                  onOpen={() =>
                    router.push(
                      `/dashboard/organizations/${orgId}/attestations/${att.id}`,
                    )
                  }
                  onReassign={() => setReassigningId(att.id)}
                />
              ))}
            </div>
          )}
        </div>
      ) : (
        <div id={tabPanelId("history")} role="tabpanel" aria-labelledby={tabId("history")}>
          {completedAttestations.length === 0 ? (
            <div className="p-8 text-center text-foreground-muted border border-border-default border-dashed rounded-xl bg-surface-2">
              <h3 className="font-semibold text-foreground mb-1">No completed reviews</h3>
              <p className="text-sm">Reviews your organization finishes will appear here.</p>
            </div>
          ) : (
            <div className="grid gap-4">
              {completedAttestations.map((att) => (
                <QueueCard
                  active={false}
                  attestation={att}
                  isAdmin={isAdmin}
                  key={att.id}
                  onOpen={() =>
                    router.push(
                      `/dashboard/organizations/${orgId}/attestations/${att.id}`,
                    )
                  }
                  onReassign={() => setReassigningId(att.id)}
                />
              ))}
            </div>
          )}
        </div>
      )}

      {reassigningId && orgId && (
        <ReassignReviewerDialog
          orgId={orgId}
          attestationId={reassigningId}
          currentMemberId={
            attestations.find((a) => a.id === reassigningId)?.reviewing_member_id
          }
          onClose={() => setReassigningId(null)}
          onDone={() => {
            setReassigningId(null);
            load(() => true);
          }}
        />
      )}
    </div>
  );
}
