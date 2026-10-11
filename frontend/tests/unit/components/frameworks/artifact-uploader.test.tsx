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
      await screen.findByText(/unsupported file type/i),
    ).toBeInTheDocument();
    // The useful half of a type rejection is what IS accepted.
    expect(await screen.findByText(/Supported types:/i)).toBeInTheDocument();
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

  it("accepts more than one file from the picker", () => {
    // The control said "Upload files" while the input took one. The team
    // pushed 56 files through production one at a time before reporting it.
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
    expect(input.multiple).toBe(true);
  });

  it("uploads every selected file, not just the first", async () => {
    vi.mocked(api.createArtifactUpload).mockReset();
    vi.mocked(api.confirmArtifact).mockReset();
    let issued = 0;
    vi.mocked(api.createArtifactUpload).mockImplementation(async () => {
      issued += 1;
      return {
        artifact_id: `art_${issued}`,
        upload_url: "https://s3.example.com/bucket",
        fields: { key: `artifacts/art_${issued}` },
      } as never;
    });
    vi.mocked(api.confirmArtifact).mockImplementation(
      async (_fw, artifactId) => ({ id: artifactId }) as never,
    );
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true } as Response));

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
      fireEvent.change(input, {
        target: {
          files: [
            new File(["x"], "a.pdf", { type: "application/pdf" }),
            new File(["x"], "b.pdf", { type: "application/pdf" }),
            new File(["x"], "c.pdf", { type: "application/pdf" }),
          ],
        },
      });

      expect(
        await screen.findByText(/3 artifacts uploaded/i),
      ).toBeInTheDocument();
      expect(api.confirmArtifact).toHaveBeenCalledTimes(3);
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("uploads the good files in a batch and names the ones it skipped", async () => {
    // One bad file must not abandon the rest — the point of a batch is that
    // the contributor does not have to babysit it — and a silently dropped
    // file is worse than a named one.
    vi.mocked(api.createArtifactUpload).mockReset();
    vi.mocked(api.confirmArtifact).mockReset();
    vi.mocked(api.createArtifactUpload).mockResolvedValue({
      artifact_id: "art_1",
      upload_url: "https://s3.example.com/bucket",
      fields: { key: "artifacts/art_1" },
    } as never);
    vi.mocked(api.confirmArtifact).mockResolvedValue({ id: "art_1" } as never);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true } as Response));

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
      fireEvent.change(input, {
        target: {
          files: [
            new File(["x"], "good.pdf", { type: "application/pdf" }),
            new File(["x"], "payload.exe", {
              type: "application/x-msdownload",
            }),
          ],
        },
      });

      expect(
        await screen.findByText(/1 artifact uploaded/i),
      ).toBeInTheDocument();
      expect(await screen.findByText(/payload\.exe/)).toBeInTheDocument();
      expect(api.confirmArtifact).toHaveBeenCalledTimes(1);
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("counts a batch against the byte cap as it goes", async () => {
    // Two 300MB files each fit under the 500MB cap alone but not together, so
    // checking every file against the pre-batch total would admit both.
    vi.mocked(api.createArtifactUpload).mockReset();
    vi.mocked(api.confirmArtifact).mockReset();
    vi.mocked(api.createArtifactUpload).mockResolvedValue({
      artifact_id: "art_1",
      upload_url: "https://s3.example.com/bucket",
      fields: { key: "artifacts/art_1" },
    } as never);
    vi.mocked(api.confirmArtifact).mockResolvedValue({ id: "art_1" } as never);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true } as Response));

    /** A PDF reporting the given byte size. */
    function sized(name: string, size: number): File {
      const file = new File(["x"], name, { type: "application/pdf" });
      Object.defineProperty(file, "size", { value: size });
      return file;
    }

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
      fireEvent.change(input, {
        target: {
          files: [
            sized("first.pdf", 300 * 1024 * 1024),
            sized("second.pdf", 300 * 1024 * 1024),
          ],
        },
      });

      expect(
        await screen.findByText(/exceed the 500 ?MB limit/i),
      ).toBeInTheDocument();
      expect(api.confirmArtifact).toHaveBeenCalledTimes(1);
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

describe("ArtifactUploader Google Drive availability", () => {
  it("offers the Drive import when the integration is enabled", () => {
    vi.stubEnv("NEXT_PUBLIC_GOOGLE_DRIVE_ENABLED", "true");
    render(
      <ArtifactUploader
        api={api}
        artifactCount={0}
        existingBytes={0}
        frameworkId="fw_drive_on"
        onUploaded={() => undefined}
      />,
    );

    expect(screen.getByText("Import from Google Drive")).toBeInTheDocument();
  });

  it("hides the Drive import while the OAuth app is unapproved", () => {
    vi.stubEnv("NEXT_PUBLIC_GOOGLE_DRIVE_ENABLED", "");
    render(
      <ArtifactUploader
        api={api}
        artifactCount={0}
        existingBytes={0}
        frameworkId="fw_drive_off"
        onUploaded={() => undefined}
      />,
    );

    expect(
      screen.queryByText("Import from Google Drive"),
    ).not.toBeInTheDocument();
  });
});
