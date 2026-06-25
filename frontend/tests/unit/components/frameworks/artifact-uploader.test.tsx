import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ArtifactUploader } from "@/components/modules/frameworks/artifact-uploader";
import {
  confirmArtifactUpload,
  requestArtifactUploadUrl,
} from "@/lib/generated/sdk.gen";

const MAX_TOTAL_BYTES = 500 * 1024 * 1024;

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  getAccessTokenHeaders: () => ({ Authorization: "Bearer access-token" }),
  describeGeneratedError: () => "The request could not be completed.",
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  client: { setConfig: vi.fn(), interceptors: { response: { use: vi.fn() } } },
  requestArtifactUploadUrl: vi.fn(),
  confirmArtifactUpload: vi.fn(),
}));

describe("ArtifactUploader", () => {
  it("blocks an over-limit upload before calling the API", async () => {
    vi.mocked(requestArtifactUploadUrl).mockReset();
    const { container } = render(
      <ArtifactUploader
        artifactCount={1}
        existingBytes={MAX_TOTAL_BYTES}
        frameworkId="fw_1"
        onUploaded={() => undefined}
      />,
    );

    const input = container.querySelector(
      'input[type="file"]',
    ) as HTMLInputElement;
    const file = new File(["x"], "too-big.pdf", { type: "application/pdf" });
    fireEvent.change(input, { target: { files: [file] } });

    expect(
      await screen.findByText(/exceed the 500 ?MB limit/i),
    ).toBeInTheDocument();
    expect(requestArtifactUploadUrl).not.toHaveBeenCalled();
  });

  it("blocks an unsupported file type before calling the API", async () => {
    vi.mocked(requestArtifactUploadUrl).mockReset();
    const { container } = render(
      <ArtifactUploader
        artifactCount={0}
        existingBytes={0}
        frameworkId="fw_1"
        onUploaded={() => undefined}
      />,
    );

    const input = container.querySelector(
      'input[type="file"]',
    ) as HTMLInputElement;
    const file = new File(["x"], "notes.txt", { type: "text/plain" });
    fireEvent.change(input, { target: { files: [file] } });

    expect(
      await screen.findByText(/file type is not supported/i),
    ).toBeInTheDocument();
    expect(requestArtifactUploadUrl).not.toHaveBeenCalled();
  });

  it("surfaces an error and clears the spinner when the S3 upload throws", async () => {
    // Reproduces the prod hang: a CORS-blocked S3 POST makes `fetch` reject.
    // Without a catch the control stayed on "Uploading..." forever. It must
    // recover to an error message and a re-armed picker instead.
    vi.mocked(requestArtifactUploadUrl).mockReset();
    vi.mocked(requestArtifactUploadUrl).mockResolvedValue({
      response: { ok: true } as Response,
      data: {
        artifact_id: "art_1",
        upload_url: "https://s3.example.com/bucket",
        fields: { key: "artifacts/art_1" },
      },
    } as never);
    const fetchMock = vi
      .fn()
      .mockRejectedValue(new TypeError("Failed to fetch"));
    vi.stubGlobal("fetch", fetchMock);

    try {
      const { container } = render(
        <ArtifactUploader
          artifactCount={0}
          existingBytes={0}
          frameworkId="fw_1"
          onUploaded={() => undefined}
        />,
      );

      const input = container.querySelector(
        'input[type="file"]',
      ) as HTMLInputElement;
      const file = new File(["x"], "deck.pdf", { type: "application/pdf" });
      fireEvent.change(input, { target: { files: [file] } });

      expect(await screen.findByText(/upload failed/i)).toBeInTheDocument();
      expect(screen.queryByText(/uploading/i)).not.toBeInTheDocument();
      expect(confirmArtifactUpload).not.toHaveBeenCalled();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("constrains the file picker to accepted types", () => {
    const { container } = render(
      <ArtifactUploader
        artifactCount={0}
        existingBytes={0}
        frameworkId="fw_1"
        onUploaded={() => undefined}
      />,
    );

    const input = container.querySelector(
      'input[type="file"]',
    ) as HTMLInputElement;
    expect(input.accept).toContain("application/pdf");
    expect(input.accept).toContain("image/png");
  });

  it("shows the total size limit and accepted file types", () => {
    render(
      <ArtifactUploader
        artifactCount={0}
        existingBytes={0}
        frameworkId="fw_1"
        onUploaded={() => undefined}
      />,
    );

    expect(screen.getByText(/500 MB total/i)).toBeInTheDocument();
    expect(screen.getByText(/PDF/i)).toBeInTheDocument();
  });

  it("prompts to choose the first artifact when none exist", () => {
    render(
      <ArtifactUploader
        artifactCount={0}
        existingBytes={0}
        frameworkId="fw_1"
        onUploaded={() => undefined}
      />,
    );

    expect(screen.getByText(/upload files/i)).toBeInTheDocument();
  });

  it("invites adding another artifact and clarifies it does not replace", () => {
    render(
      <ArtifactUploader
        artifactCount={2}
        existingBytes={0}
        frameworkId="fw_1"
        onUploaded={() => undefined}
      />,
    );

    expect(screen.getByText(/add another artifact/i)).toBeInTheDocument();
    expect(screen.getByText(/does not replace/i)).toBeInTheDocument();
  });
});
