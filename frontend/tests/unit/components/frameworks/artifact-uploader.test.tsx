import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ArtifactUploader } from "@/components/modules/frameworks/artifact-uploader";
import { requestArtifactUploadUrl } from "@/lib/generated/sdk.gen";

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
