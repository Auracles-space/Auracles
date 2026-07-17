"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";

import { useOrganization } from "@/components/modules/organizations/organization-context";
import { listOrgAttestationsV1OrgsOrgIdAttestationsGet } from "@/lib/generated/sdk.gen";
import { getAccessTokenHeaders, describeGeneratedError } from "@/lib/auth/form-client";
import { OrgAttestationItem } from "@/lib/generated/types.gen";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { Badge } from "@/components/ui/badge";
import { Tabs, tabPanelId, tabId } from "@/components/ui/tabs";
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
const COMPLETED_QUEUE_STATUSES = [
  "report_submitted",
  "released",
  "resolved",
  "refunded",
  "closed",
];

/** Badge variant for an in-flight attestation status. */
function queueStatusVariant(
  status: string,
): "info" | "default" | "warning" | "error" {
  if (status === "accepted") return "info";
  if (status === "disputed") return "error";
  if (status === "in_review") return "default";
  return "warning";
}

/** Title-case a raw status/outcome token for display. */
function humanize(value: string): string {
  return value.replace(/_/g, " ");
}

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
        <h2 className="text-xl font-semibold tracking-tight text-foreground">Attestation Queue</h2>
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
              <h3 className="font-semibold text-foreground mb-1">Queue Empty</h3>
              <p className="text-sm">There are no active attestations in your queue.</p>
            </div>
          ) : (
            <div className="grid gap-4">
              {activeAttestations.map((att) => (
                <div key={att.id} className="border border-border-default rounded-xl p-5 bg-surface-1 shadow-sm flex flex-col md:flex-row md:items-center justify-between gap-4">
                  <div className="space-y-1">
                    <div className="flex flex-wrap items-center gap-2">
                      {att.unread_answer ? (
                        <span
                          aria-label="Clarification answer awaiting your review"
                          role="img"
                          className="h-2.5 w-2.5 flex-shrink-0 rounded-full bg-error"
                        />
                      ) : null}
                      <span className="font-semibold text-foreground">
                        {att.target_title ?? (
                          <span className="capitalize">{att.target_type}</span>
                        )}
                      </span>
                      <Badge variant={queueStatusVariant(att.status)}>
                        {humanize(att.status)}
                      </Badge>
                      {att.unread_answer ? (
                        <Badge variant="error">Answer received</Badge>
                      ) : null}
                    </div>
                    <div className="text-sm text-foreground-muted">
                      {att.review_type ? `${att.review_type} review` : "Attestation"}
                      {" · "}
                      <span className="capitalize">{att.target_type}</span>
                    </div>
                    {isAdmin && (
                      <div className="text-sm text-foreground-muted">
                        Assigned to: {att.reviewing_member_name ?? "Unassigned"}
                      </div>
                    )}
                  </div>

                  <div className="flex flex-col sm:flex-row gap-2">
                    <Button
                      variant="secondary"
                      disabled={!isAdmin}
                      onClick={() => setReassigningId(att.id)}
                    >
                      Reassign
                    </Button>
                    <Button
                      variant="secondary"
                      onClick={() =>
                        router.push(
                          `/dashboard/organizations/${orgId}/attestations/${att.id}`,
                        )
                      }
                    >
                      Workspace
                    </Button>
                  </div>
                </div>
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
                <div key={att.id} className="border border-border-default rounded-xl p-5 bg-surface-1 shadow-sm flex flex-col md:flex-row md:items-center justify-between gap-4">
                  <div className="space-y-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-semibold text-foreground">
                        {att.target_title ?? (
                          <span className="capitalize">{att.target_type}</span>
                        )}
                      </span>
                      {att.outcome ? (
                        <Badge variant="default" className="capitalize">
                          {humanize(att.outcome)}
                        </Badge>
                      ) : null}
                    </div>
                    <div className="text-sm text-foreground-muted">
                      {att.review_type ? `${att.review_type} review` : "Attestation"}
                      {" · "}
                      <span className="capitalize">{humanize(att.status)}</span>
                      {att.updated_at
                        ? ` · ${new Date(att.updated_at).toLocaleDateString()}`
                        : null}
                    </div>
                    {isAdmin && (
                      <div className="text-sm text-foreground-muted">
                        Reviewed by: {att.reviewing_member_name ?? "—"}
                      </div>
                    )}
                  </div>

                  <div className="flex flex-col sm:flex-row gap-2">
                    <Button
                      variant="secondary"
                      onClick={() =>
                        router.push(
                          `/dashboard/organizations/${orgId}/attestations/${att.id}`,
                        )
                      }
                    >
                      View
                    </Button>
                  </div>
                </div>
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
