import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PreviewArtifactBlock } from "@/components/modules/explore/preview-artifact-block";
import type { ExploreFrameworkDetail } from "@/lib/generated/types.gen";

/** Build a minimal ExploreFrameworkDetail fixture for the preview block. */
function detail(
  overrides: Partial<ExploreFrameworkDetail> = {},
): ExploreFrameworkDetail {
  return {
    preview_url: null,
    artifacts: [
      {
        id: "artifact-1",
        name: "playbook.docx",
        mime_type: "application/pdf",
        file_size: 2048,
      },
    ],
    ...overrides,
  } as ExploreFrameworkDetail;
}

describe("PreviewArtifactBlock", () => {
  it("offers the open link when a preview url is present", () => {
    render(
      <PreviewArtifactBlock
        framework={detail({ preview_url: "https://files.example/preview" })}
      />,
    );

    expect(
      screen.getByRole("link", { name: /open preview artifact/i }),
    ).toBeInTheDocument();
  });

  it("shows a neutral empty state, not a warning, when no preview is set", () => {
    render(<PreviewArtifactBlock framework={detail({ preview_url: null })} />);

    expect(
      screen.queryByRole("link", { name: /open preview artifact/i }),
    ).not.toBeInTheDocument();
    expect(screen.getByText(/no public preview/i)).toBeInTheDocument();
    expect(
      screen.queryByText(/preview artifact is not available/i),
    ).not.toBeInTheDocument();
  });

  it("still lists the artifact manifest when there is no preview", () => {
    render(<PreviewArtifactBlock framework={detail({ preview_url: null })} />);

    expect(screen.getByText("playbook.docx")).toBeInTheDocument();
  });
});
