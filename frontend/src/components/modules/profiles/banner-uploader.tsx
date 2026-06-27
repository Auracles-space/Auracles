"use client";

/**
 * Profile banner uploader.
 *
 * Two-step presigned upload to the public avatars bucket (banners/ prefix):
 * request a target, POST the file straight to S3, then confirm so the backend
 * verifies the object and persists banner_url. Banners are wide cover images, so
 * unlike the avatar there is no crop step — the image is uploaded as selected.
 */
import { useRef, useState } from "react";

import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import {
  confirmBannerUploadV1ProfilesMeBannerConfirmPost,
  requestBannerUploadUrlV1ProfilesMeBannerUploadUrlPost,
} from "@/lib/generated/sdk.gen";

const ALLOWED_TYPES = ["image/png", "image/jpeg", "image/webp"];
const MAX_BYTES = 5 * 1024 * 1024;

type BannerUploaderProps = {
  bannerUrl: string | null;
  onUploaded: (bannerUrl: string) => void;
};

/**
 * Render the banner preview plus a "Change banner" upload control.
 *
 * @param props - Current banner URL and a callback invoked with the new public
 *   URL once the upload is confirmed.
 */
export function BannerUploader({ bannerUrl, onUploaded }: BannerUploaderProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  /**
   * Validate, upload, and confirm the selected banner file.
   *
   * @param file - The user-selected image file.
   */
  async function handleFile(file: File): Promise<void> {
    setError(null);
    if (!ALLOWED_TYPES.includes(file.type)) {
      setError("Choose a PNG, JPEG, or WebP image.");
      return;
    }
    if (file.size > MAX_BYTES) {
      setError("Image must be 5MB or smaller.");
      return;
    }

    setBusy(true);
    try {
      configureBrowserClient();
      const target = await requestBannerUploadUrlV1ProfilesMeBannerUploadUrlPost({
        body: {
          filename: file.name,
          mime_type: file.type,
          file_size: file.size,
        },
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

      const confirmed = await confirmBannerUploadV1ProfilesMeBannerConfirmPost({
        body: { file_key: target.data.file_key },
        headers: getAccessTokenHeaders(),
      });
      if (confirmed.error || !confirmed.data) {
        setError(describeGeneratedError(confirmed.error));
        return;
      }
      onUploaded(confirmed.data.banner_url ?? target.data.banner_url);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-2">
      <div className="relative h-28 w-full overflow-hidden rounded-2xl border border-border-default bg-surface-2 sm:h-36">
        {bannerUrl ? (
          <div
            aria-hidden="true"
            className="absolute inset-0 bg-cover bg-center"
            style={{ backgroundImage: `url(${bannerUrl})` }}
          />
        ) : (
          <div className="absolute inset-0 flex items-center justify-center text-xs text-foreground-subtle">
            No banner yet
          </div>
        )}

        {/* Edit pencil overlay button at the bottom-right of the banner pane */}
        <div className="absolute bottom-2 right-2 sm:bottom-3 sm:right-3 z-10">
          <button
            aria-label="Change banner"
            disabled={busy}
            onClick={() => inputRef.current?.click()}
            type="button"
            className="flex h-9 w-9 items-center justify-center rounded-full border border-border-default bg-surface-1/90 backdrop-blur-sm shadow-md transition-all hover:bg-surface-2 hover:scale-[1.05] active:scale-[0.95] disabled:cursor-not-allowed disabled:opacity-60 cursor-pointer"
          >
            {busy ? (
              <svg className="h-4 w-4 animate-spin text-foreground-muted" viewBox="0 0 24 24" fill="none">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
              </svg>
            ) : (
              <svg
                className="h-4 w-4 text-foreground"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                strokeWidth={2}
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z"
                />
              </svg>
            )}
          </button>
        </div>
      </div>
      <input
        accept={ALLOWED_TYPES.join(",")}
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
      <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between px-1">
        <p className="text-xs text-foreground-subtle">
          Wide image. PNG, JPEG, or WebP. Max 5MB.
        </p>
        {error ? <p className="text-sm text-error font-medium">{error}</p> : null}
      </div>
    </div>
  );
}
