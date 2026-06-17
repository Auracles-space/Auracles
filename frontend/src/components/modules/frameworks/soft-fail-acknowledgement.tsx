"use client";

/**
 * External rarity soft-fail acknowledgement.
 *
 * Acknowledgement records Contributor awareness; it does not bypass backend
 * hard gates such as virus or PII failures.
 */
import { useRouter } from "next/navigation";
import { useState } from "react";

import { acknowledgeFrameworkSoftFail } from "@/lib/generated/sdk.gen";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";

type SoftFailAcknowledgementProps = {
  frameworkId: string;
};

/**
 * Render acknowledgement action for rarity soft fails.
 *
 * @param props - Framework id.
 */
export function SoftFailAcknowledgement({
  frameworkId,
}: SoftFailAcknowledgementProps) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);

  async function handleAcknowledge() {
    configureBrowserClient();
    const result = await acknowledgeFrameworkSoftFail({
      headers: getAccessTokenHeaders(),
      path: { framework_id: frameworkId },
    });
    if (!result.response.ok) {
      setError(describeGeneratedError(result.error));
      return;
    }
    router.refresh();
  }

  return (
    <div className="min-w-0 rounded-2xl border border-warning/30 bg-warning/10 p-4 shadow-sm">
      <p className="text-sm text-warning">
        External rarity needs Contributor acknowledgement before retrying
        publish.
      </p>
      <button
        className="mt-3 min-h-12 rounded-xl border border-warning px-4 py-2 text-sm font-semibold text-warning hover:bg-warning/10"
        onClick={handleAcknowledge}
        type="button"
      >
        Acknowledge soft fail
      </button>
      {error ? <p className="mt-2 text-sm text-error">{error}</p> : null}
    </div>
  );
}
