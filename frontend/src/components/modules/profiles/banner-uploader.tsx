"use client";

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { Button } from "@/components/ui/button";
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
// Enforce a maximum file selection size of 10MB to prevent browser UI lockup during load
const MAX_SELECT_BYTES = 10 * 1024 * 1024;
const CROP_CONTAINER_WIDTH = 270;
const CROP_CONTAINER_HEIGHT = 90;

type BannerUploaderProps = {
  bannerUrl: string | null;
  onUploaded: (bannerUrl: string) => void;
};

/**
 * Render the avatar preview plus a circular cropping and size optimization uploader.
 */
export function BannerUploader({
  bannerUrl,
  onUploaded,
}: BannerUploaderProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [mounted, setMounted] = useState(false);

  const [isDragging, setIsDragging] = useState(false);

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  };
  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
  };
  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    const file = e.dataTransfer.files?.[0];
    if (file) handleFileSelect(file);
  };


  // Cropping State
  const [tempImageSrc, setTempImageSrc] = useState<string | null>(null);
  const [originalFile, setOriginalFile] = useState<File | null>(null);
  const [zoom, setZoom] = useState(1);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const [dragStart, setDragStart] = useState<{ x: number; y: number } | null>(null);
  const [imageSize, setImageSize] = useState({ width: 0, height: 0 });

  useEffect(() => {
    setMounted(true);
    return () => setMounted(false);
  }, []);
  const [naturalSize, setNaturalSize] = useState({ width: 0, height: 0 });



  // Drag Panning Mouse Listener
  useEffect(() => {
    if (!dragStart) return;

    function handleMouseMove(e: MouseEvent) {
      if (!dragStart) return;
      const dx = e.clientX - dragStart.x;
      const dy = e.clientY - dragStart.y;

      const W = imageSize.width * zoom;
      const H = imageSize.height * zoom;
      const maxX = Math.max(0, (W - CROP_CONTAINER_WIDTH) / 2);
      const maxY = Math.max(0, (H - CROP_CONTAINER_HEIGHT) / 2);

      setOffset({
        x: Math.min(maxX, Math.max(-maxX, dx)),
        y: Math.min(maxY, Math.max(-maxY, dy)),
      });
    }

    function handleMouseUp() {
      setDragStart(null);
    }

    window.addEventListener("mousemove", handleMouseMove);
    window.addEventListener("mouseup", handleMouseUp);
    return () => {
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", handleMouseUp);
    };
  }, [dragStart, imageSize, zoom]);

  // Drag Panning Touch Listener for Mobile
  useEffect(() => {
    if (!dragStart) return;

    function handleTouchMove(e: TouchEvent) {
      if (!dragStart) return;
      const touch = e.touches[0];
      if (!touch) return;
      const dx = touch.clientX - dragStart.x;
      const dy = touch.clientY - dragStart.y;

      const W = imageSize.width * zoom;
      const H = imageSize.height * zoom;
      const maxX = Math.max(0, (W - CROP_CONTAINER_WIDTH) / 2);
      const maxY = Math.max(0, (H - CROP_CONTAINER_HEIGHT) / 2);

      setOffset({
        x: Math.min(maxX, Math.max(-maxX, dx)),
        y: Math.min(maxY, Math.max(-maxY, dy)),
      });
    }

    function handleTouchEnd() {
      setDragStart(null);
    }

    window.addEventListener("touchmove", handleTouchMove, { passive: true });
    window.addEventListener("touchend", handleTouchEnd);
    return () => {
      window.removeEventListener("touchmove", handleTouchMove);
      window.removeEventListener("touchend", handleTouchEnd);
    };
  }, [dragStart, imageSize, zoom]);

  const handleMouseDown = (e: React.MouseEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragStart({ x: e.clientX - offset.x, y: e.clientY - offset.y });
  };

  const handleTouchStart = (e: React.TouchEvent<HTMLDivElement>) => {
    const touch = e.touches[0];
    if (touch) {
      setDragStart({ x: touch.clientX - offset.x, y: touch.clientY - offset.y });
    }
  };

  const handleImageLoad = (e: React.SyntheticEvent<HTMLImageElement>) => {
    const img = e.currentTarget;
    const nw = img.naturalWidth;
    const nh = img.naturalHeight;
    setNaturalSize({ width: nw, height: nh });

    const ar = nw / nh;
    const TARGET_AR = 3; // 1200 / 400
    let w = CROP_CONTAINER_WIDTH;
    let h = CROP_CONTAINER_HEIGHT;
    if (ar > TARGET_AR) {
      // Image is wider than target
      h = CROP_CONTAINER_HEIGHT;
      w = CROP_CONTAINER_HEIGHT * ar;
    } else {
      w = CROP_CONTAINER_WIDTH;
      h = CROP_CONTAINER_WIDTH / ar;
    }
    setImageSize({ width: w, height: h });
    setOffset({ x: 0, y: 0 });
    setZoom(1);
  };

  const handleZoomChange = (newZoom: number) => {
    setZoom(newZoom);
    const W = imageSize.width * newZoom;
    const H = imageSize.height * newZoom;
    const maxX = Math.max(0, (W - CROP_CONTAINER_WIDTH) / 2);
    const maxY = Math.max(0, (H - CROP_CONTAINER_HEIGHT) / 2);
    setOffset((prev) => ({
      x: Math.min(maxX, Math.max(-maxX, prev.x)),
      y: Math.min(maxY, Math.max(-maxY, prev.y)),
    }));
  };

  /**
   * Select a file and open the editor canvas.
   */
  function handleFileSelect(file: File): void {
    setError(null);
    if (!ALLOWED_TYPES.includes(file.type)) {
      setError("Choose a PNG, JPEG, or WebP image.");
      return;
    }
    if (file.size > MAX_SELECT_BYTES) {
      setError("Image must be 10MB or smaller.");
      return;
    }

    setOriginalFile(file);
    const reader = new FileReader();
    reader.onload = () => {
      setTempImageSrc(reader.result as string);
      setZoom(1);
      setOffset({ x: 0, y: 0 });
    };
    reader.readAsDataURL(file);
  }

  /**
   * Crop image using canvas, compress, and run S3 presigned upload.
   */
  const handleCropApply = async () => {
    if (!originalFile || !tempImageSrc) return;

    setBusy(true);
    try {
      const img = new Image();
      img.src = tempImageSrc;
      await new Promise((resolve, reject) => {
        img.onload = resolve;
        img.onerror = reject;
      });

      const canvas = document.createElement("canvas");
      canvas.width = 400;
      canvas.height = 400;
      const ctx = canvas.getContext("2d");
      if (!ctx) throw new Error("Could not get 2d context");

      const W = imageSize.width * zoom;
      const H = imageSize.height * zoom;

      const scaleX = naturalSize.width / W;
      const scaleY = naturalSize.height / H;

      const sx = (W / 2 - CROP_CONTAINER_WIDTH / 2 - offset.x) * scaleX;
      const sy = (H / 2 - CROP_CONTAINER_HEIGHT / 2 - offset.y) * scaleY;
      const sw = CROP_CONTAINER_WIDTH * scaleX;
      const sh = CROP_CONTAINER_HEIGHT * scaleY;

      canvas.width = 1200;
      canvas.height = 400;
      ctx.drawImage(img, sx, sy, sw, sh, 0, 0, 1200, 400);

      canvas.toBlob(
        async (blob) => {
          if (!blob) {
            setError("Could not crop image.");
            setBusy(false);
            return;
          }

          const croppedFile = new File([blob], originalFile.name.replace(/\.[^/.]+$/, "") + ".jpg", {
            type: "image/jpeg",
          });

          await uploadCroppedFile(croppedFile);
        },
        "image/jpeg",
        0.85
      );
    } catch {
      setError("Failed to process image.");
      setBusy(false);
    }
  };

  async function uploadCroppedFile(file: File): Promise<void> {
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
      setTempImageSrc(null);
      setOriginalFile(null);
    } catch {
      setError("An unexpected error occurred during upload.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-2">
      <div
        className={[
          "relative h-28 w-full overflow-hidden rounded-2xl border transition-all sm:h-36 group",
          isDragging ? "border-accent bg-accent/5 ring-2 ring-accent" : "border-border-default bg-surface-2"
        ].join(" ")}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
      >
        {bannerUrl ? (
          <div
            aria-hidden="true"
            className="absolute inset-0 bg-cover bg-center"
            style={{ backgroundImage: `url(${bannerUrl})` }}
          />
        ) : (
          <div className="absolute inset-0 flex items-center justify-center text-xs text-foreground-subtle pointer-events-none">
            No banner yet
          </div>
        )}

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
            handleFileSelect(file);
          }
          event.target.value = "";
        }}
        ref={inputRef}
        type="file"
      />
      <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between px-1">
        <p className="text-xs text-foreground-subtle">Wide image. PNG, JPEG, or WebP. Max 10MB.</p>
        {error ? <p className="text-sm text-error font-medium">{error}</p> : null}
      </div>

      {/* LinkedIn-style Crop Modal overlay portalled to body to escape parent stacking context */}
      {mounted && tempImageSrc && createPortal(
        <div className="fixed inset-0 z-50 grid place-items-center bg-black/40 p-4 animate-[fade-in_120ms_ease-out]">
          <div
            className="w-full max-w-sm rounded-2xl border border-border-default bg-surface-1 p-5 shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
              Edit Banner
            </p>
            <h2 className="mt-1 font-heading text-lg font-bold text-foreground">
              Crop and position your banner
            </h2>

            {/* Circular crop container */}
            <div className="mt-4 flex justify-center">
              <div
                className="relative h-[90px] w-[270px] overflow-hidden rounded-xl border border-border-strong bg-surface-2 cursor-grab active:cursor-grabbing select-none"
                onMouseDown={handleMouseDown}
                onTouchStart={handleTouchStart}
              >
                {/* Image under the mask */}
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={tempImageSrc}
                  alt="Crop preview"
                  className="absolute pointer-events-none max-w-none origin-center"
                  style={{
                    transform: `translate(${offset.x}px, ${offset.y}px)`,
                    left: "50%",
                    top: "50%",
                    width: imageSize.width * zoom,
                    height: imageSize.height * zoom,
                    marginLeft: -(imageSize.width * zoom) / 2,
                    marginTop: -(imageSize.height * zoom) / 2,
                  }}
                  onLoad={handleImageLoad}
                />

                {/* Circular mask overlay */}
                <div className="absolute inset-0 rounded-xl border-2 border-accent pointer-events-none ring-[100px] ring-black/45" />
              </div>
            </div>

            {/* Zoom Slider */}
            <div className="mt-4 space-y-1">
              <div className="flex items-center justify-between text-xs text-foreground-muted font-medium">
                <span>Zoom</span>
                <span>{Math.round(zoom * 100)}%</span>
              </div>
              <input
                type="range"
                min="1"
                max="3"
                step="0.01"
                value={zoom}
                onChange={(e) => handleZoomChange(parseFloat(e.target.value))}
                className="w-full accent-accent h-1 bg-surface-3 rounded-lg appearance-none cursor-pointer"
              />
            </div>

            {/* Action buttons */}
            <div className="mt-5 flex gap-2 justify-end">
              <Button
                variant="secondary"
                onClick={() => {
                  setTempImageSrc(null);
                  setOriginalFile(null);
                }}
              >
                Cancel
              </Button>
              <Button
                onClick={handleCropApply}
                loading={busy}
              >
                Apply
              </Button>
            </div>
          </div>
        </div>,
        document.body
      )}
    </div>
  );
}
