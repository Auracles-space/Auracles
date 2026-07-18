import {
  fireEvent,
  render,
  screen,
  waitFor,
  type RenderResult,
} from "@testing-library/react";
import { type ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { FrameworkEditor } from "@/components/modules/frameworks/framework-editor";
import { ToastProvider } from "@/components/ui/toast";
import type {
  ArtifactResponse,
  FrameworkResponse,
} from "@/lib/generated/types.gen";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/dashboard/frameworks/fw_1",
}));

const { api, frameworkApiFor } = vi.hoisted(() => ({
  api: {
    confirmArtifact: vi.fn(),
    create: vi.fn(),
    createArtifactUpload: vi.fn(),
    deleteArtifact: vi.fn(),
    get: vi.fn(),
    list: vi.fn(),
    listArtifacts: vi.fn(),
    publish: vi.fn(),
    relist: vi.fn(),
    startVersion: vi.fn(),
    submit: vi.fn(),
    unpublish: vi.fn(),
    update: vi.fn(),
    updatePricing: vi.fn(),
  },
  frameworkApiFor: vi.fn(),
}));

const grantRequiredMessage =
  "You need the Contributor right for this organization. Ask an admin to add you to a team with the Contributor capability.";

vi.mock("@/lib/frameworks/framework-api", () => ({
  CONTRIBUTOR_GRANT_REQUIRED_MESSAGE:
    "You need the Contributor right for this organization. Ask an admin to add you to a team with the Contributor capability.",
  frameworkApiFor,
  isFrameworkApiErrorCode: (error: unknown, code: string) =>
    error instanceof Error && "code" in error && error.code === code,
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
  unpublishFramework: vi.fn(),
  relistFramework: vi.fn(),
}));

/** Render the editor beneath the toast provider its actions depend on. */
function renderWithToast(ui: ReactElement): RenderResult {
  return render(<ToastProvider>{ui}</ToastProvider>);
}

/** Render the personal seller editor used by regression tests. */
function renderPersonalEditor(): RenderResult {
  return renderWithToast(
    <FrameworkEditor
      basePath="/dashboard/frameworks"
      canManageLiveState
      frameworkId="fw_1"
      seller={{ kind: "user" }}
    />,
  );
}

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
    source_kind: "upload",
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
  api.get.mockResolvedValue(framework);
  api.listArtifacts.mockResolvedValue(artifacts);
}

describe("FrameworkEditor", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    frameworkApiFor.mockReturnValue(api);
  });

  it("hides the new-version action for an unpublished draft", async () => {
    mockLoad(makeFramework({ status: "draft" }));

    renderPersonalEditor();

    await screen.findByText("Test Framework");
    expect(api.get).toHaveBeenCalledWith("fw_1");
    expect(api.listArtifacts).toHaveBeenCalledWith("fw_1");
    expect(
      screen.queryByRole("button", { name: /start draft version/i }),
    ).not.toBeInTheDocument();
  });

  it("renders a friendly empty state for a missing organization grant", async () => {
    api.get.mockRejectedValue(
      Object.assign(new Error("Request failed"), {
        code: "capability_grant_required",
      }),
    );
    api.listArtifacts.mockResolvedValue([]);

    renderWithToast(
      <FrameworkEditor
        frameworkId="fw_1"
        seller={{ kind: "org", orgId: "org-1" }}
        canManageLiveState={false}
        basePath="/dashboard/organizations/org-1/frameworks"
      />,
    );

    expect(await screen.findByText(grantRequiredMessage)).toBeInTheDocument();
    expect(screen.queryByText(/^request failed$/i)).not.toBeInTheDocument();
  });

  it("shows the new-version action once the framework is published", async () => {
    mockLoad(makeFramework({ status: "published" }));

    renderPersonalEditor();

    await screen.findByText("Test Framework");
    expect(
      screen.getByRole("button", { name: /start draft version/i }),
    ).toBeInTheDocument();
  });

  it("starts a new version through the selected seller adapter", async () => {
    const updated = makeFramework({ status: "draft", version: "1.1.0" });
    mockLoad(makeFramework({ status: "published" }));
    api.startVersion.mockResolvedValue(updated);

    renderPersonalEditor();
    fireEvent.click(
      await screen.findByRole("button", { name: /start draft version/i }),
    );

    await waitFor(() => {
      expect(api.startVersion).toHaveBeenCalledWith(
        "fw_1",
        expect.objectContaining({ change_type: "improvement" }),
      );
    });
  });

  it("hides live-state controls from a non-admin organization author", async () => {
    mockLoad(makeFramework({ status: "published" }));

    renderWithToast(
      <FrameworkEditor
        frameworkId="fw_1"
        seller={{ kind: "org", orgId: "org-1" }}
        canManageLiveState={false}
        basePath="/dashboard/organizations/org-1/frameworks"
      />,
    );

    await screen.findByText("Test Framework");
    expect(
      screen.queryByRole("button", { name: /delist from marketplace/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /start draft version/i }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText(/^pricing$/i)).not.toBeInTheDocument();
  });

  it("shows organization pricing to admins and surfaces adapter failures", async () => {
    mockLoad(makeFramework({ status: "published" }));
    api.updatePricing.mockRejectedValue(
      new Error("Organization pricing could not be updated."),
    );

    renderWithToast(
      <FrameworkEditor
        frameworkId="fw_1"
        seller={{ kind: "org", orgId: "org-1" }}
        canManageLiveState
        basePath="/dashboard/organizations/org-1/frameworks"
      />,
    );

    await screen.findByText("Test Framework");
    fireEvent.click(screen.getByRole("button", { name: /save pricing/i }));

    expect(
      await screen.findByText(/organization pricing could not be updated/i),
    ).toBeInTheDocument();
    expect(api.updatePricing).toHaveBeenCalledWith(
      "fw_1",
      expect.objectContaining({ pricing: expect.any(Object) }),
    );
  });

  it("lets a delisted framework edit metadata, relist, or start a new version", async () => {
    mockLoad(makeFramework({ status: "unpublished" }));

    renderPersonalEditor();

    await screen.findByText("Test Framework");
    // Metadata edits save in place; relist and new version are also offered.
    expect(
      screen.getByRole("button", { name: /save changes/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /relist on marketplace/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /start draft version/i }),
    ).toBeInTheDocument();
  });

  it("keeps metadata editable on a live framework but locks it mid-pipeline", async () => {
    mockLoad(makeFramework({ status: "published" }));
    const { unmount } = renderPersonalEditor();
    await screen.findByText("Test Framework");
    expect(
      screen.getByRole("button", { name: /save changes/i }),
    ).toBeInTheDocument();
    unmount();

    mockLoad(makeFramework({ status: "submitted" }));
    renderPersonalEditor();
    await screen.findByText("Test Framework");
    expect(
      screen.queryByRole("button", { name: /save changes/i }),
    ).not.toBeInTheDocument();
  });

  it("removes a draft artifact and drops it from the manifest", async () => {
    mockLoad(makeFramework({ status: "draft" }), [
      makeArtifact({ id: "art_1", name: "Operating Model.pdf" }),
    ]);
    api.deleteArtifact.mockResolvedValue(undefined);

    renderPersonalEditor();

    await screen.findByText("Operating Model.pdf");
    fireEvent.click(
      screen.getByRole("button", { name: /remove operating model\.pdf/i }),
    );

    await waitFor(() => {
      expect(screen.queryByText("Operating Model.pdf")).not.toBeInTheDocument();
    });
    // Delete must go through the seller adapter so org Frameworks reach the
    // organization endpoint rather than the personal-ownership one.
    expect(api.deleteArtifact).toHaveBeenCalledWith("fw_1", "art_1");
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

    renderPersonalEditor();

    await screen.findByText("Operating Model.pdf");
    expect(
      screen.queryByRole("button", { name: /remove operating model\.pdf/i }),
    ).not.toBeInTheDocument();
  });

  it("disables Run publishing checks when no artifact is attached", async () => {
    mockLoad(makeFramework({ status: "draft" }), []);

    renderPersonalEditor();

    const button = await screen.findByRole("button", {
      name: /run publishing checks/i,
    });
    expect(button).toBeDisabled();
  });

  it("enables Run publishing checks once an artifact is attached", async () => {
    mockLoad(makeFramework({ status: "draft" }), [
      makeArtifact({ id: "art_1", processing_status: "processed" }),
    ]);

    renderPersonalEditor();

    const button = await screen.findByRole("button", {
      name: /run publishing checks/i,
    });
    expect(button).toBeEnabled();
  });

  it("submits publishing checks through the selected seller adapter", async () => {
    const framework = makeFramework({ status: "draft" });
    mockLoad(framework, [
      makeArtifact({ id: "art_1", processing_status: "processed" }),
    ]);
    api.submit.mockResolvedValue(
      makeFramework({ status: "submitted" }),
    );

    renderPersonalEditor();
    fireEvent.click(
      await screen.findByRole("button", { name: /run publishing checks/i }),
    );

    await waitFor(() => expect(api.submit).toHaveBeenCalledWith("fw_1"));
  });

  it("updates metadata through the selected seller adapter", async () => {
    const framework = makeFramework({ status: "draft" });
    mockLoad(framework);
    api.update.mockResolvedValue(framework);

    renderPersonalEditor();
    fireEvent.click(
      await screen.findByRole("button", { name: /save changes/i }),
    );

    await waitFor(() => {
      expect(api.update).toHaveBeenCalledWith(
        "fw_1",
        expect.objectContaining({ title: "Test Framework" }),
      );
    });
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

    renderPersonalEditor();

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

      renderPersonalEditor();
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

    renderPersonalEditor();

    await screen.findByText("Operating Model.pdf");
    expect(
      screen.queryByRole("button", { name: /remove operating model\.pdf/i }),
    ).not.toBeInTheDocument();
  });
});
