import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { OrganizationLogoUploader } from "@/components/modules/organizations/organization-logo-uploader";
import {
  confirmOrgLogoUploadV1OrgsOrgIdLogoConfirmPost,
  requestOrgLogoUploadUrlV1OrgsOrgIdLogoUploadUrlPost,
} from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: vi.fn(() => "The request could not be completed."),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer test-token" })),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  requestOrgLogoUploadUrlV1OrgsOrgIdLogoUploadUrlPost: vi.fn(),
  confirmOrgLogoUploadV1OrgsOrgIdLogoConfirmPost: vi.fn(),
}));

function pngFile(sizeBytes = 1024): File {
  const file = new File(["x"], "logo.png", { type: "image/png" });
  Object.defineProperty(file, "size", { value: sizeBytes });
  return file;
}

describe("OrganizationLogoUploader", () => {
  beforeEach(() => {
    vi.mocked(requestOrgLogoUploadUrlV1OrgsOrgIdLogoUploadUrlPost).mockReset();
    vi.mocked(confirmOrgLogoUploadV1OrgsOrgIdLogoConfirmPost).mockReset();
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(null, { status: 204 })),
    );
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("runs the presigned upload flow and reports the new logo URL", async () => {
    vi.stubGlobal(
      "Image",
      class {
        onload: (() => void) | null = null;
        onerror: (() => void) | null = null;

        set src(_value: string) {
          queueMicrotask(() => {
            this.onload?.();
          });
        }
      } as typeof Image,
    );
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({
      drawImage: vi.fn(),
    } as unknown as CanvasRenderingContext2D);
    vi.spyOn(HTMLCanvasElement.prototype, "toBlob").mockImplementation(
      (callback) => {
        callback(new Blob(["cropped"], { type: "image/jpeg" }));
      },
    );
    vi.mocked(
      requestOrgLogoUploadUrlV1OrgsOrgIdLogoUploadUrlPost,
    ).mockResolvedValue({
      data: {
        upload_url: "https://s3.test/upload",
        fields: { key: "org-logos/org-1/abc.png", policy: "p" },
        file_key: "org-logos/org-1/abc.png",
        max_size: 5 * 1024 * 1024,
        expires_in: 900,
      },
      error: undefined,
      request: new Request("http://t"),
      response: new Response(null, { status: 200 }),
    } as never);
    vi.mocked(
      confirmOrgLogoUploadV1OrgsOrgIdLogoConfirmPost,
    ).mockResolvedValue({
      data: { logo_key: "org-logos/org-1/abc.png", logo_url: "https://cdn.test/abc.png" },
      error: undefined,
      request: new Request("http://t"),
      response: new Response(null, { status: 200 }),
    } as never);

    const onUploaded = vi.fn();
    render(
      <OrganizationLogoUploader
        orgId="org-1"
        logoUrl={null}
        name="Acme"
        canEdit
        onUploaded={onUploaded}
      />,
    );

    const input = screen.getByLabelText(/upload logo/i);
    fireEvent.change(input, { target: { files: [pngFile()] } });
    const preview = await screen.findByAltText(/crop preview/i);
    Object.defineProperty(preview, "naturalWidth", { value: 600 });
    Object.defineProperty(preview, "naturalHeight", { value: 400 });
    fireEvent.load(preview);
    fireEvent.click(screen.getByRole("button", { name: /^apply$/i }));

    await waitFor(() => {
      expect(onUploaded).toHaveBeenCalledWith("https://cdn.test/abc.png");
    });
    // Presigned POST includes the S3 policy fields plus the file.
    expect(global.fetch).toHaveBeenCalledWith(
      "https://s3.test/upload",
      expect.objectContaining({ method: "POST" }),
    );
    expect(
      confirmOrgLogoUploadV1OrgsOrgIdLogoConfirmPost,
    ).toHaveBeenCalledWith(
      expect.objectContaining({
        path: { org_id: "org-1" },
        body: { file_key: "org-logos/org-1/abc.png" },
      }),
    );
  });

  it("rejects a non-image file before requesting a target", async () => {
    const onUploaded = vi.fn();
    render(
      <OrganizationLogoUploader
        orgId="org-1"
        logoUrl={null}
        name="Acme"
        canEdit
        onUploaded={onUploaded}
      />,
    );

    const pdf = new File(["x"], "doc.pdf", { type: "application/pdf" });
    fireEvent.change(screen.getByLabelText(/upload logo/i), {
      target: { files: [pdf] },
    });

    await screen.findByText(/Choose a PNG, JPEG, or WebP image/i);
    expect(
      requestOrgLogoUploadUrlV1OrgsOrgIdLogoUploadUrlPost,
    ).not.toHaveBeenCalled();
    expect(onUploaded).not.toHaveBeenCalled();
  });

  it("opens the crop editor as a bottom sheet on mobile with a 44px zoom control", async () => {
    render(
      <OrganizationLogoUploader
        orgId="org-1"
        logoUrl={null}
        name="Acme"
        canEdit
        onUploaded={vi.fn()}
      />,
    );

    fireEvent.change(screen.getByLabelText(/upload logo/i), {
      target: { files: [pngFile()] },
    });
    await screen.findByAltText(/crop preview/i);

    // Same pattern as ConfirmDialog: the overlay carries the dialog role.
    const overlay = screen.getByRole("dialog");
    expect(overlay?.className).toMatch(/place-items-end/);
    expect(overlay?.className).toMatch(/p-0/);
    expect(overlay?.className).toMatch(/sm:place-items-center/);
    expect(overlay?.className).toMatch(/sm:p-4/);

    const slider = screen.getByLabelText(/zoom/i);
    expect(slider).toHaveAttribute("type", "range");
    expect(slider.className).toMatch(/\bh-2\b/);
    expect(slider.closest("label")?.className).toMatch(/py-4/);
  });

  it("hides the upload control when the member cannot edit", () => {
    render(
      <OrganizationLogoUploader
        orgId="org-1"
        logoUrl="https://cdn.test/current.png"
        name="Acme"
        canEdit={false}
        onUploaded={vi.fn()}
      />,
    );

    expect(screen.queryByLabelText(/upload logo/i)).not.toBeInTheDocument();
  });
});
