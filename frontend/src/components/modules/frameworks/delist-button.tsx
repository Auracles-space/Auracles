"use client";

/**
 * Contributor delist button.
 *
 * UI says "Delist from marketplace" even though the backend endpoint is named
 * `unpublish`; existing licensees keep access to purchased versions.
 */
import { useRouter } from "next/navigation";
import { useState } from "react";

import { unpublishFramework } from "@/lib/generated/sdk.gen";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";

type DelistButtonProps = {
  frameworkId: string;
};

/**
 * Render a confirmation-backed delist action.
 *
 * @param props - Framework id.
 */
export function DelistButton({ frameworkId }: DelistButtonProps) {
  const router = useRouter();
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleDelist() {
    configureBrowserClient();
    const result = await unpublishFramework({
      headers: getAccessTokenHeaders(),
      path: { framework_id: frameworkId },
    });
    if (!result.response.ok) {
      setError(describeGeneratedError(result.error));
      return;
    }
    setConfirming(false);
    router.refresh();
  }

  return (
    <div>
      <button
        className="inline-flex min-h-11 items-center justify-center rounded-[6px] border border-error px-4 py-2 text-sm font-semibold text-error transition hover:bg-error/10"
        onClick={() => setConfirming(true)}
        type="button"
      >
        Delist from marketplace
      </button>
      {confirming ? (
        <div className="mt-3 rounded-2xl border border-border-default bg-background p-4 shadow-sm">
          <p className="text-sm text-foreground">
            Delisting hides this Framework from the catalog. Existing licensees
            keep access to the version they paid for.
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            <button
              className="min-h-11 rounded-[6px] border border-error px-4 py-2 text-sm font-semibold text-error hover:bg-error/10"
              onClick={handleDelist}
              type="button"
            >
              Confirm delist
            </button>
            <button
              className="min-h-11 rounded-[6px] border border-border-default px-4 py-2 text-sm font-semibold text-foreground hover:bg-surface-2"
              onClick={() => setConfirming(false)}
              type="button"
            >
              Cancel
            </button>
          </div>
        </div>
      ) : null}
      {error ? <p className="mt-2 text-sm text-error">{error}</p> : null}
    </div>
  );
}
