/**
 * Admin attestor application actions — the calibration fixture picker.
 *
 * With no fixtures the picker was an empty dropdown and Start trial stayed
 * disabled without saying why; it must point the admin to the Fixtures tab.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AttestorApplicationActions } from "@/components/modules/admin/attestors/attestor-application-actions";
import type { ApplicationGates } from "@/components/modules/admin/attestors/attestor-gates";

const gates: ApplicationGates = {
  underReview: true,
  decided: false,
  kybDone: true,
  trialPassed: false,
  trialSubmitted: false,
  awaitingNominee: false,
  canStartTrial: true,
  canApprove: false,
  canNeedsInfo: true,
  canReject: true,
  nextStep: "Start the calibration trial.",
  capability: { canSuspend: false, canReinstate: false, canRevoke: false },
};

function renderActions(fixtures: { id: string; title: string; review_type: string }[]) {
  render(
    <AttestorApplicationActions
      busy={false}
      fixtures={fixtures}
      gates={gates}
      onApprove={vi.fn()}
      onNeedsInfo={vi.fn()}
      onReject={vi.fn()}
      onStartTrial={vi.fn()}
      orgName="Ikeji Advisory"
    />,
  );
}

describe("AttestorApplicationActions fixture picker", () => {
  it("points the admin to the Fixtures tab when no fixture exists", () => {
    renderActions([]);

    expect(screen.getByText(/No calibration fixtures yet/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Create one on the Fixtures tab/i })).toHaveAttribute(
      "href",
      "/admin/attestors?tab=fixtures",
    );
    expect(screen.queryByLabelText("Calibration fixture for Ikeji Advisory")).toBeNull();
    expect(screen.getByRole("button", { name: "Start trial" })).toBeDisabled();
  });

  it("lists fixtures in the picker once they exist", () => {
    renderActions([{ id: "fx-1", title: "Governance audit fixture", review_type: "framework" }]);

    expect(screen.getByRole("option", { name: "Governance audit fixture (framework)" })).toBeInTheDocument();
    expect(screen.queryByText(/No calibration fixtures yet/i)).toBeNull();
  });
});
