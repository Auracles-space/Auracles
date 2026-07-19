"use client";

/**
 * External rarity soft-fail acknowledgement.
 *
 * Acknowledgement records Contributor awareness; it does not bypass backend
 * hard gates such as virus or PII failures. Routes through the seller adapter
 * so organization-owned Frameworks hit the organization endpoint; the personal
 * SDK path 404s on them.
 */
import { useState } from "react";

import type { FrameworkApi } from "@/lib/frameworks/framework-api";

type SoftFailAcknowledgementProps = {
  api: FrameworkApi;
  frameworkId: string;
  onAcknowledged: () => void;
};

/**
 * Render acknowledgement action for rarity soft fails.
 *
 * @param props - Seller adapter, Framework id, and post-acknowledge reload.
 */
export function SoftFailAcknowledgement({
  api,
  frameworkId,
  onAcknowledged,
}: SoftFailAcknowledgementProps) {
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function handleAcknowledge() {
    setError(null);
    setSaving(true);
    try {
      await api.acknowledgeSoftFail(frameworkId);
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : "The request could not be completed.",
      );
      setSaving(false);
      return;
    }
    setSaving(false);
    onAcknowledged();
  }

  return (
    <div className="min-w-0 rounded-2xl border border-warning/30 bg-warning/10 p-4 shadow-sm">
      <p className="text-sm text-warning">
        External rarity needs Contributor acknowledgement before retrying
        publish.
      </p>
      <button
        className="mt-3 min-h-12 rounded-xl border border-warning px-4 py-2 text-sm font-semibold text-warning hover:bg-warning/10 disabled:opacity-60 disabled:cursor-not-allowed"
        disabled={saving}
        onClick={handleAcknowledge}
        type="button"
      >
        Acknowledge soft fail
      </button>
      {error ? <p className="mt-2 text-sm text-error">{error}</p> : null}
    </div>
  );
}
