import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ArtifactUploader } from "@/components/modules/frameworks/artifact-uploader";
import type { FrameworkApi } from "@/lib/frameworks/framework-api";

const MAX_TOTAL_BYTES = 500 * 1024 * 1024;

const api = {
  confirmArtifact: vi.fn(),
  createArtifactUpload: vi.fn(),
} as unknown as FrameworkApi;

describe("ArtifactUploader", () => {
  it("blocks an over-limit upload before calling the API", async () => {
    vi.mocked(api.createArtifactUpload).mockReset();
    const { container } = render(
      <ArtifactUploader
        api={api}
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
    expect(api.createArtifactUpload).not.toHaveBeenCalled();
  });

  it("blocks an unsupported file type before calling the API", async () => {
    vi.mocked(api.createArtifactUpload).mockReset();
    const { container } = render(
      <ArtifactUploader
        api={api}
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
    expect(api.createArtifactUpload).not.toHaveBeenCalled();
  });

  it("surfaces an error and clears the spinner when the S3 upload throws", async () => {
    // Reproduces the prod hang: a CORS-blocked S3 POST makes `fetch` reject.
    // Without a catch the control stayed on "Uploading..." forever. It must
    // recover to an error message and a re-armed picker instead.
    vi.mocked(api.createArtifactUpload).mockReset();
    vi.mocked(api.createArtifactUpload).mockResolvedValue({
      artifact_id: "art_1",
      upload_url: "https://s3.example.com/bucket",
      fields: { key: "artifacts/art_1" },
    } as never);
    const fetchMock = vi
      .fn()
      .mockRejectedValue(new TypeError("Failed to fetch"));
    vi.stubGlobal("fetch", fetchMock);

    try {
      const { container } = render(
        <ArtifactUploader
          api={api}
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
      expect(api.confirmArtifact).not.toHaveBeenCalled();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("constrains the file picker to accepted types", () => {
    const { container } = render(
      <ArtifactUploader
        api={api}
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
        api={api}
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
        api={api}
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
        api={api}
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
