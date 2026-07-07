"use client";

import { useState } from "react";
import {
  createOrgAttestorApplication,
  submitOrgAttestorApplication,
  updateOrgAttestorApplication,
} from "@/lib/generated/sdk.gen";
import type { OrgAttestorApplicationResponse } from "@/lib/generated/types.gen";
import { describeGeneratedError, getAccessTokenHeaders } from "@/lib/auth/form-client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";

export function ApplyGate({
  orgId,
  application,
  onChange,
}: {
  orgId: string;
  application: OrgAttestorApplicationResponse | null;
  onChange: () => void;
}) {
  const isDraft = !application || application.status === "draft";
  const isNeedsInfo = application?.status === "needs_info";
  const canEdit = isDraft || isNeedsInfo;

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [formData, setFormData] = useState({
    legal_name: application?.legal_name || "",
    credentials_summary: application?.credentials_summary || "",
    professional_references: application?.professional_references || "",
    sample_work_url: (application?.sample_work as { url: string })?.url || "",
    incorporation_doc_keys: application?.incorporation_doc_keys || [],
    sectors: application?.sectors || [],
    framework_categories: application?.framework_categories || [],
    jurisdictions: application?.jurisdictions || [],
  });

  async function handleSaveDraft() {
    setLoading(true);
    setError(null);
    try {
      const body = {
        legal_name: formData.legal_name,
        credentials_summary: formData.credentials_summary,
        professional_references: formData.professional_references,
        sample_work: { url: formData.sample_work_url },
        incorporation_doc_keys: formData.incorporation_doc_keys,
        sectors: formData.sectors,
        framework_categories: formData.framework_categories,
        jurisdictions: formData.jurisdictions,
      };
      let res;
      if (!application) {
        res = await createOrgAttestorApplication({
          path: { org_id: orgId },
          body,
          headers: getAccessTokenHeaders(),
        });
      } else {
        res = await updateOrgAttestorApplication({
          path: { org_id: orgId },
          body,
          headers: getAccessTokenHeaders(),
        });
      }
      if (res.error) {
        setError(describeGeneratedError(res.error));
      } else {
        onChange();
      }
    } catch (e) {
      setError("An unexpected error occurred.");
    } finally {
      setLoading(false);
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      // First save draft
      const body = {
        legal_name: formData.legal_name,
        credentials_summary: formData.credentials_summary,
        professional_references: formData.professional_references,
        sample_work: { url: formData.sample_work_url },
        incorporation_doc_keys: formData.incorporation_doc_keys,
        sectors: formData.sectors,
        framework_categories: formData.framework_categories,
        jurisdictions: formData.jurisdictions,
      };
      
      let updateRes;
      if (!application) {
        updateRes = await createOrgAttestorApplication({
          path: { org_id: orgId },
          body,
          headers: getAccessTokenHeaders(),
        });
      } else {
        updateRes = await updateOrgAttestorApplication({
          path: { org_id: orgId },
          body,
          headers: getAccessTokenHeaders(),
        });
      }

      if (updateRes.error) {
        setError(describeGeneratedError(updateRes.error));
        setLoading(false);
        return;
      }

      const res = await submitOrgAttestorApplication({
        path: { org_id: orgId },
        headers: getAccessTokenHeaders(),
      });
      if (res.error) {
        setError(describeGeneratedError(res.error));
      } else {
        onChange();
      }
    } catch (e) {
      setError("An unexpected error occurred.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="rounded-xl border border-border-default bg-surface-1 p-5 shadow-sm">
      {isNeedsInfo && application?.admin_feedback && (
        <div className="mb-6 rounded-lg border border-warning/30 bg-warning/10 p-4 text-sm text-warning">
          <span className="mb-1 block font-bold">Admin Feedback:</span>
          {application.admin_feedback}
        </div>
      )}

      {error && (
        <div className="mb-6 rounded-lg border border-error/50 bg-error/5 p-4 text-sm text-error">
          {error}
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label htmlFor="legal_name" className="mb-1 block text-sm font-semibold text-foreground">
            Legal Name
          </label>
          <Input
            id="legal_name"
            disabled={!canEdit}
            value={formData.legal_name}
            onChange={(e) => setFormData({ ...formData, legal_name: e.target.value })}
            placeholder="Audit Ltd."
          />
        </div>

        <div>
          <label
            htmlFor="credentials_summary"
            className="mb-1 block text-sm font-semibold text-foreground"
          >
            Credentials Summary
          </label>
          <Textarea
            id="credentials_summary"
            disabled={!canEdit}
            value={formData.credentials_summary}
            onChange={(e) => setFormData({ ...formData, credentials_summary: e.target.value })}
            placeholder="Summary of relevant experience..."
          />
        </div>

        <div>
          <label htmlFor="sample_work" className="mb-1 block text-sm font-semibold text-foreground">
            Sample Work (URL)
          </label>
          <Input
            id="sample_work"
            disabled={!canEdit}
            value={formData.sample_work_url}
            onChange={(e) => setFormData({ ...formData, sample_work_url: e.target.value })}
            placeholder="https://..."
          />
        </div>

        <div>
          <label htmlFor="references" className="mb-1 block text-sm font-semibold text-foreground">
            Professional References
          </label>
          <Textarea
            id="references"
            disabled={!canEdit}
            value={formData.professional_references}
            onChange={(e) => setFormData({ ...formData, professional_references: e.target.value })}
            placeholder="Names and contact info of references..."
          />
        </div>

        <div className="flex gap-3 pt-4">
          {canEdit && (
            <>
              <Button type="button" variant="secondary" onClick={handleSaveDraft} disabled={loading}>
                Save Draft
              </Button>
              <Button type="submit" disabled={loading} loading={loading}>
                Submit Application
              </Button>
            </>
          )}
        </div>
      </form>
    </div>
  );
}
