import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { FrameworkEditor } from "@/components/modules/frameworks/framework-editor";
import {
  deleteArtifact,
  getContributorFramework,
  listFrameworkArtifacts,
} from "@/lib/generated/sdk.gen";
import type {
  ArtifactResponse,
  FrameworkResponse,
} from "@/lib/generated/types.gen";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/dashboard/frameworks/fw_1",
}));

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  getAccessTokenHeaders: () => ({ Authorization: "Bearer access-token" }),
  describeGeneratedError: () => "The request could not be completed.",
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  client: { setConfig: vi.fn(), interceptors: { response: { use: vi.fn() } } },
  getContributorFramework: vi.fn(),
  listFrameworkArtifacts: vi.fn(),
  deleteArtifact: vi.fn(),
  submitFramework: vi.fn(),
  updateFramework: vi.fn(),
  createFrameworkVersion: vi.fn(),
  confirmArtifactUpload: vi.fn(),
  requestArtifactUploadUrl: vi.fn(),
  acknowledgeSimilarityNotice: vi.fn(),
  publishFramework: vi.fn(),
  delistFramework: vi.fn(),
}));

function makeFramework(
  overrides: Partial<FrameworkResponse> = {},
): FrameworkResponse {
  return {
    id: "fw_1",
    title: "Test Framework",
    status: "draft",
    version: "1.0.0",
    description: "A test framework.",
    category: "framework",
    sector: "technology",
    industry: "software_engineering",
    function: "operations",
    org_size: "sme",
    tags: [],
    pricing: {
      price: "100.00",
      currency: "USD",
      license_types: ["single_user"],
    },
    ...overrides,
  } as FrameworkResponse;
}

function makeArtifact(
  overrides: Partial<ArtifactResponse> = {},
): ArtifactResponse {
  return {
    created_at: "2026-06-08T10:00:00Z",
    file_key: "private/frameworks/artifact.pdf",
    file_size: 1024,
    framework_id: "fw_1",
    id: "art_1",
    mime_type: "application/pdf",
    name: "Operating Model.pdf",
    pii_detected: false,
    pii_review_needed: false,
    processing_status: "processed",
    rarity_score: "0.91",
    near_duplicate_blocked: false,
    redaction_accepted: false,
    redaction_available: false,
    redaction_status: null,
    scan_status: "clean",
    similarity_notice: null,
    ...overrides,
  } as ArtifactResponse;
}

function mockLoad(
  framework: FrameworkResponse,
  artifacts: ArtifactResponse[] = [],
): void {
  vi.mocked(getContributorFramework).mockResolvedValue({
    data: framework,
    error: undefined,
    response: new Response(null, { status: 200 }),
  } as never);
  vi.mocked(listFrameworkArtifacts).mockResolvedValue({
    data: artifacts,
    error: undefined,
    response: new Response(null, { status: 200 }),
  } as never);
}

describe("FrameworkEditor", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("hides the new-version action for an unpublished draft", async () => {
    mockLoad(makeFramework({ status: "draft" }));

    render(<FrameworkEditor frameworkId="fw_1" />);

    await screen.findByText("Test Framework");
    expect(
      screen.queryByRole("button", { name: /start draft version/i }),
    ).not.toBeInTheDocument();
  });

  it("shows the new-version action once the framework is published", async () => {
    mockLoad(makeFramework({ status: "published" }));

    render(<FrameworkEditor frameworkId="fw_1" />);

    await screen.findByText("Test Framework");
    expect(
      screen.getByRole("button", { name: /start draft version/i }),
    ).toBeInTheDocument();
  });

  it("removes a draft artifact and drops it from the manifest", async () => {
    mockLoad(makeFramework({ status: "draft" }), [
      makeArtifact({ id: "art_1", name: "Operating Model.pdf" }),
    ]);
    vi.mocked(deleteArtifact).mockResolvedValue({
      data: undefined,
      error: undefined,
      response: new Response(null, { status: 204 }),
    } as never);

    render(<FrameworkEditor frameworkId="fw_1" />);

    await screen.findByText("Operating Model.pdf");
    fireEvent.click(
      screen.getByRole("button", { name: /remove operating model\.pdf/i }),
    );

    await waitFor(() => {
      expect(screen.queryByText("Operating Model.pdf")).not.toBeInTheDocument();
    });
    expect(deleteArtifact).toHaveBeenCalledWith(
      expect.objectContaining({
        path: { framework_id: "fw_1", artifact_id: "art_1" },
      }),
    );
  });

  it("hides the artifact remove control while the artifact is still processing", async () => {
    mockLoad(makeFramework({ status: "draft" }), [
      makeArtifact({
        id: "art_1",
        name: "Operating Model.pdf",
        processing_status: "processing",
        scan_status: "pending",
      }),
    ]);

    render(<FrameworkEditor frameworkId="fw_1" />);

    await screen.findByText("Operating Model.pdf");
    expect(
      screen.queryByRole("button", { name: /remove operating model\.pdf/i }),
    ).not.toBeInTheDocument();
  });

  it("disables Submit for publishing when no artifact is attached", async () => {
    mockLoad(makeFramework({ status: "draft" }), []);

    render(<FrameworkEditor frameworkId="fw_1" />);

    const button = await screen.findByRole("button", {
      name: /submit for publishing/i,
    });
    expect(button).toBeDisabled();
  });

  it("enables Submit for publishing once an artifact is attached", async () => {
    mockLoad(makeFramework({ status: "draft" }), [
      makeArtifact({ id: "art_1", processing_status: "processed" }),
    ]);

    render(<FrameworkEditor frameworkId="fw_1" />);

    const button = await screen.findByRole("button", {
      name: /submit for publishing/i,
    });
    expect(button).toBeEnabled();
  });

  it("shows the artifact remove control on a pipeline_failed framework", async () => {
    mockLoad(makeFramework({ status: "pipeline_failed" }), [
      makeArtifact({
        id: "art_1",
        name: "Operating Model.pdf",
        processing_status: "flagged_pii",
        pii_review_needed: true,
      }),
    ]);

    render(<FrameworkEditor frameworkId="fw_1" />);

    expect(
      await screen.findByRole("button", {
        name: /remove operating model\.pdf/i,
      }),
    ).toBeInTheDocument();
  });

  it("polls and reflects pipeline completion without a manual reload", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      mockLoad(makeFramework({ status: "draft" }), [
        makeArtifact({
          id: "art_1",
          processing_status: "processing",
          scan_status: "pending",
        }),
      ]);

      render(<FrameworkEditor frameworkId="fw_1" />);
      await screen.findByText("Test Framework");

      // Worker finishes: artifact gets PII-flagged, framework fails the gate.
      mockLoad(makeFramework({ status: "pipeline_failed" }), [
        makeArtifact({
          id: "art_1",
          processing_status: "flagged_pii",
          scan_status: "clean",
          pii_review_needed: true,
        }),
      ]);

      await vi.advanceTimersByTimeAsync(3000);

      expect(
        await screen.findByText("PII review required"),
      ).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("hides the artifact remove control once published", async () => {
    mockLoad(makeFramework({ status: "published" }), [
      makeArtifact({ id: "art_1", name: "Operating Model.pdf" }),
    ]);

    render(<FrameworkEditor frameworkId="fw_1" />);

    await screen.findByText("Operating Model.pdf");
    expect(
      screen.queryByRole("button", { name: /remove operating model\.pdf/i }),
    ).not.toBeInTheDocument();
  });
});
