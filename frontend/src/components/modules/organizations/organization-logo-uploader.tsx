"use client";

/**
 * Organization logo uploader.
 *
 * Shows the current org logo (or an initial fallback) and, for members who can
 * edit, a verified upload control. Uploads run the two-step presigned flow:
 * request a target, POST the file straight to S3, then confirm so the backend
 * persists the org-namespaced key and returns the public logo URL.
 */
import { useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import {
  confirmOrgLogoUploadV1OrgsOrgIdLogoConfirmPost,
  requestOrgLogoUploadUrlV1OrgsOrgIdLogoUploadUrlPost,
} from "@/lib/generated/sdk.gen";

const ALLOWED_TYPES = ["image/png", "image/jpeg", "image/webp"];
// Match the backend cap (5MB) so oversize files fail fast in the browser.
const MAX_BYTES = 5 * 1024 * 1024;

type OrganizationLogoUploaderProps = {
  /** Organization the logo belongs to. */
  orgId: string;
  /** Current public logo URL, or null when none is set. */
  logoUrl: string | null;
  /** Organization name — drives the initial fallback tile. */
  name: string;
  /** Whether the current member may change the logo (admin/owner). */
  canEdit: boolean;
  /** Called with the new public logo URL after a successful upload. */
  onUploaded: (logoUrl: string) => void;
};

/**
 * Render the org logo preview plus a verified upload control for admins.
 *
 * @param orgId - Organization id.
 * @param logoUrl - Current logo URL, or null.
 * @param name - Org name for the fallback initial.
 * @param canEdit - Whether to show the upload control.
 * @param onUploaded - Callback with the new logo URL.
 */
export function OrganizationLogoUploader({
  orgId,
  logoUrl,
  name,
  canEdit,
  onUploaded,
}: OrganizationLogoUploaderProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const initial = name.trim().charAt(0).toUpperCase() || "O";

  async function handleFile(file: File): Promise<void> {
    setError(null);
    if (!ALLOWED_TYPES.includes(file.type)) {
      setError("Choose a PNG, JPEG, or WebP image.");
      return;
    }
    if (file.size > MAX_BYTES) {
      setError("Logo must be 5MB or smaller.");
      return;
    }

    setBusy(true);
    try {
      configureBrowserClient();
      const target = await requestOrgLogoUploadUrlV1OrgsOrgIdLogoUploadUrlPost({
        path: { org_id: orgId },
        body: { mime_type: file.type, file_size: file.size },
        headers: getAccessTokenHeaders(),
      });
      if (target.error || !target.data) {
        setError(describeGeneratedError(target.error));
        return;
      }

      const form = new FormData();
      for (const [key, value] of Object.entries(target.data.fields)) {
        form.append(key, String(value));
      }
      form.append("file", file);
      const upload = await fetch(target.data.upload_url, {
        method: "POST",
        body: form,
      });
      if (!upload.ok) {
        setError("The upload could not be completed. Try again.");
        return;
      }

      const confirmed = await confirmOrgLogoUploadV1OrgsOrgIdLogoConfirmPost({
        path: { org_id: orgId },
        body: { file_key: target.data.file_key },
        headers: getAccessTokenHeaders(),
      });
      if (confirmed.error || !confirmed.data) {
        setError(describeGeneratedError(confirmed.error));
        return;
      }

      if (confirmed.data.logo_url) {
        onUploaded(confirmed.data.logo_url);
      }
    } catch {
      setError("An unexpected error occurred during upload.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex items-center gap-4">
      <div className="flex h-20 w-20 shrink-0 items-center justify-center overflow-hidden rounded-2xl border border-border-default bg-surface-2">
        {logoUrl ? (
          <div
            aria-hidden="true"
            className="h-full w-full bg-cover bg-center"
            style={{ backgroundImage: `url(${logoUrl})` }}
          />
        ) : (
          <span className="font-heading text-2xl font-extrabold text-accent">
            {initial}
          </span>
        )}
      </div>
      {canEdit ? (
        <div className="space-y-2">
          <input
            accept={ALLOWED_TYPES.join(",")}
            aria-label="Upload logo"
            className="hidden"
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) {
                void handleFile(file);
              }
              event.target.value = "";
            }}
            ref={inputRef}
            type="file"
          />
          <Button
            loading={busy}
            onClick={() => inputRef.current?.click()}
            type="button"
            variant="secondary"
          >
            {logoUrl ? "Change logo" : "Upload logo"}
          </Button>
          <p className="text-xs text-foreground-subtle">
            PNG, JPEG, or WebP. Max 5MB.
          </p>
          {error ? <p className="text-sm text-error">{error}</p> : null}
        </div>
      ) : null}
    </div>
  );
}
