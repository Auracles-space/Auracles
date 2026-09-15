import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AdminCalibrationFixturesPanel } from "@/components/modules/admin/admin-calibration-fixtures-panel";
import {
  adminCreateCalibrationFixtureV1AdminOrgAttestorApplicationsCalibrationFixturesPost as createFixture,
  adminListCalibrationFixturesV1AdminOrgAttestorApplicationsCalibrationFixturesGet as listFixtures,
  adminListFixtureArtifactsV1AdminOrgAttestorApplicationsCalibrationFixturesFrameworkIdArtifactsGet as listFixtureArtifacts,
  adminListTrialAnswerKeysV1AdminOrgAttestorApplicationsCalibrationFixturesFrameworkIdAnswerKeysGet as listAnswerKeys,
  adminUpsertTrialAnswerKeyV1AdminOrgAttestorApplicationsCalibrationFixturesFrameworkIdAnswerKeyPut as upsertAnswerKey,
} from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: vi.fn(() => "err"),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer admin" })),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  adminListCalibrationFixturesV1AdminOrgAttestorApplicationsCalibrationFixturesGet: vi.fn(),
  adminCreateCalibrationFixtureV1AdminOrgAttestorApplicationsCalibrationFixturesPost: vi.fn(),
  adminListFixtureArtifactsV1AdminOrgAttestorApplicationsCalibrationFixturesFrameworkIdArtifactsGet: vi.fn(),
  adminCreateFixtureArtifactUploadUrlV1AdminOrgAttestorApplicationsCalibrationFixturesFrameworkIdArtifactsUploadUrlPost: vi.fn(),
  adminConfirmFixtureArtifactV1AdminOrgAttestorApplicationsCalibrationFixturesFrameworkIdArtifactsConfirmPost: vi.fn(),
  adminDeleteFixtureArtifactV1AdminOrgAttestorApplicationsCalibrationFixturesFrameworkIdArtifactsArtifactIdDelete: vi.fn(),
  adminListTrialAnswerKeysV1AdminOrgAttestorApplicationsCalibrationFixturesFrameworkIdAnswerKeysGet: vi.fn(),
  adminUpsertTrialAnswerKeyV1AdminOrgAttestorApplicationsCalibrationFixturesFrameworkIdAnswerKeyPut: vi.fn(),
}));

const ok = <T,>(data: T) => ({
  data,
  error: undefined,
  request: new Request("http://test.local"),
  response: new Response(null, { status: 200 }),
});

describe("AdminCalibrationFixturesPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(listFixtures).mockResolvedValue(
      ok({ fixtures: [{ id: "fw-1", title: "Quality Sample", review_type: "quality" }] }) as never,
    );
    vi.mocked(listFixtureArtifacts).mockResolvedValue(
      ok({
        artifacts: [
          { id: "art-1", name: "sample.pdf", mime_type: "application/pdf", scan_status: "clean" },
        ],
      }) as never,
    );
    vi.mocked(listAnswerKeys).mockResolvedValue(
      ok({
        review_type: "quality",
        rows: [
          { dimension_id: "dim-1", label: "Governance", expected_score: 4, tolerance: 1 },
        ],
      }) as never,
    );
    vi.mocked(upsertAnswerKey).mockResolvedValue(ok(undefined) as never);
    vi.mocked(createFixture).mockResolvedValue(
      ok({ id: "fw-2", title: "New One", review_type: "compliance" }) as never,
    );
  });

  it("lists fixtures and creates a new one", async () => {
    render(<AdminCalibrationFixturesPanel />);
    await waitFor(() => expect(screen.getByText(/Quality Sample/)).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText(/Fixture title/i), {
      target: { value: "New One" },
    });
    fireEvent.change(screen.getByLabelText(/Fixture description/i), {
      target: { value: "A new fixture." },
    });
    fireEvent.click(screen.getByRole("button", { name: /Create fixture/i }));

    await waitFor(() =>
      expect(vi.mocked(createFixture)).toHaveBeenCalledWith(
        expect.objectContaining({
          body: { title: "New One", description: "A new fixture.", review_type: "quality" },
        }),
      ),
    );
  });

  it("expands a fixture showing artifacts, scan status, and readiness", async () => {
    render(<AdminCalibrationFixturesPanel />);
    await waitFor(() => expect(screen.getByText(/Quality Sample/)).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: /Quality Sample/i }));

    expect(await screen.findByText(/sample\.pdf/)).toBeInTheDocument();
    expect(screen.getByText("clean")).toBeInTheDocument();
    expect(screen.getByText(/Ready to assign in a trial/i)).toBeInTheDocument();
  });

  it("saves an answer-key row", async () => {
    render(<AdminCalibrationFixturesPanel />);
    await waitFor(() => expect(screen.getByText(/Quality Sample/)).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /Quality Sample/i }));
    await screen.findByText(/Governance/);

    fireEvent.click(screen.getByRole("button", { name: /^Save$/i }));

    await waitFor(() =>
      expect(vi.mocked(upsertAnswerKey)).toHaveBeenCalledWith(
        expect.objectContaining({
          path: { framework_id: "fw-1" },
          body: { dimension_id: "dim-1", expected_score: 4, tolerance: 1 },
        }),
      ),
    );
  });

  describe("answer-key rows", () => {
    const twoRows = () =>
      vi.mocked(listAnswerKeys).mockResolvedValue(
        ok({
          review_type: "quality",
          rows: [
            { dimension_id: "dim-1", label: "Governance", expected_score: null, tolerance: null },
            { dimension_id: "dim-2", label: "Clarity", expected_score: null, tolerance: null },
          ],
        }) as never,
      );

    async function openFixture() {
      render(<AdminCalibrationFixturesPanel />);
      await waitFor(() => expect(screen.getByText(/Quality Sample/)).toBeInTheDocument());
      fireEvent.click(screen.getByRole("button", { name: /Quality Sample/i }));
      await screen.findByText("Clarity");
      return screen.getAllByRole("button", { name: /^Save$/i });
    }

    it("confirms the saved row and leaves Upload and the other rows alone", async () => {
      // A shared busy flag disabled every Save and spun the Upload button, and
      // nothing on the row said the save happened.
      twoRows();
      const [first, second] = await openFixture();

      fireEvent.click(first);

      expect(await screen.findByText("Saved")).toBeInTheDocument();
      expect(second).toBeEnabled();
      expect(screen.getByRole("button", { name: /^Upload$/i })).not.toHaveAttribute("aria-busy", "true");
      // The row is updated in place rather than by reloading the whole fixture.
      expect(vi.mocked(listAnswerKeys)).toHaveBeenCalledTimes(1);
    });

    it("keeps other rows saveable while one save is still in flight", async () => {
      twoRows();
      vi.mocked(upsertAnswerKey).mockReturnValue(new Promise(() => {}) as never);
      const [first, second] = await openFixture();

      fireEvent.click(first);

      await waitFor(() => expect(first).toBeDisabled());
      expect(second).toBeEnabled();
    });

    it("shows a failed save on its own row", async () => {
      twoRows();
      vi.mocked(upsertAnswerKey).mockRejectedValue(new Error("network down"));
      const [first, second] = await openFixture();

      fireEvent.click(first);

      expect(await screen.findByText(/Not saved/)).toBeInTheDocument();
      expect(first).toBeEnabled();
      expect(second).toBeEnabled();
    });
  });
});
