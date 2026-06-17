import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ArtifactUploader } from "@/components/modules/frameworks/artifact-uploader";

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
  it("shows the total size limit and accepted file types", () => {
    render(
      <ArtifactUploader
        artifactCount={0}
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
        frameworkId="fw_1"
        onUploaded={() => undefined}
      />,
    );

    expect(screen.getByText(/choose artifact/i)).toBeInTheDocument();
  });

  it("invites adding another artifact and clarifies it does not replace", () => {
    render(
      <ArtifactUploader
        artifactCount={2}
        frameworkId="fw_1"
        onUploaded={() => undefined}
      />,
    );

    expect(screen.getByText(/add another artifact/i)).toBeInTheDocument();
    expect(screen.getByText(/does not replace/i)).toBeInTheDocument();
  });
});
