import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AttestorApplicationPanel } from "@/components/modules/attestation/attestation-workspaces";
import {
  listMyAttestorApplications,
  submitAttestorApplication,
} from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/auth/form-client")>(
    "@/lib/auth/form-client",
  );
  return {
    ...actual,
    configureBrowserClient: vi.fn(),
    getAccessTokenHeaders: vi.fn(() => ({})),
  };
});

vi.mock("@/lib/generated/sdk.gen", () => ({
  listMyAttestorApplications: vi.fn(),
  submitAttestorApplication: vi.fn(),
  updateAttestorApplication: vi.fn(),
  withdrawAttestorApplication: vi.fn(),
}));

function application(overrides = {}) {
  return {
    admin_feedback: null,
    created_at: "2026-06-21T10:00:00Z",
    credentials_summary: "Ten plus years of security auditing experience.",
    id: "app-1",
    jurisdictions: ["US"],
    professional_references: "Jane Doe, CISO",
    reviewed_at: null,
    reviewed_by: null,
    sample_work: {},
    specializations: ["ISO 27001"],
    status: "pending",
    user_id: "user-1",
    ...overrides,
  };
}

const okResponse = new Response(null, { status: 200 });

beforeEach(() => {
  vi.mocked(listMyAttestorApplications).mockResolvedValue({
    data: { applications: [] },
    error: undefined,
    response: okResponse,
  } as never);
  vi.mocked(submitAttestorApplication).mockReset();
});

/**
 * Fill the four application fields. Order matches the rendered textboxes:
 * specializations, jurisdictions, credentials summary, references.
 */
function fillFields(values: {
  specializations: string;
  jurisdictions: string;
  summary: string;
  references: string;
}) {
  const boxes = screen.getAllByRole("textbox");
  fireEvent.change(boxes[0], { target: { value: values.specializations } });
  fireEvent.change(boxes[1], { target: { value: values.jurisdictions } });
  fireEvent.change(boxes[2], { target: { value: values.summary } });
  fireEvent.change(boxes[3], { target: { value: values.references } });
}

describe("AttestorApplicationPanel submit gating", () => {
  it("keeps submit disabled when the credentials summary is too short", async () => {
    render(<AttestorApplicationPanel />);
    await waitFor(() =>
      expect(listMyAttestorApplications).toHaveBeenCalled(),
    );

    fillFields({
      specializations: "ISO 27001",
      jurisdictions: "US",
      summary: "too short",
      references: "Jane Doe, CISO",
    });

    expect(
      screen.getByRole("button", { name: /submit application/i }),
    ).toBeDisabled();
  });

  it("enables submit once all fields meet the backend minimums", async () => {
    render(<AttestorApplicationPanel />);
    await waitFor(() =>
      expect(listMyAttestorApplications).toHaveBeenCalled(),
    );

    fillFields({
      specializations: "ISO 27001",
      jurisdictions: "US",
      summary: "Ten plus years auditing security programs.",
      references: "Jane Doe, CISO",
    });

    expect(
      screen.getByRole("button", { name: /submit application/i }),
    ).toBeEnabled();
  });

  it("hides the create form while an application is pending and edits in place", async () => {
    vi.mocked(listMyAttestorApplications).mockResolvedValue({
      data: { applications: [application()] },
      error: undefined,
      response: okResponse,
    } as never);

    render(<AttestorApplicationPanel />);
    await waitFor(() =>
      expect(listMyAttestorApplications).toHaveBeenCalled(),
    );

    // Pending application: create form hidden, edit/withdraw offered.
    expect(
      screen.queryByRole("button", { name: /submit application/i }),
    ).not.toBeInTheDocument();
    expect(screen.getByText(/awaiting admin review/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /^edit$/i }));
    expect(
      screen.getByRole("button", { name: /update application/i }),
    ).toBeInTheDocument();
  });

  it("surfaces the admin's reason on a rejected application", async () => {
    vi.mocked(listMyAttestorApplications).mockResolvedValue({
      data: {
        applications: [
          application({
            status: "rejected",
            admin_feedback: "Need a verifiable professional reference.",
          }),
        ],
      },
      error: undefined,
      response: okResponse,
    } as never);

    render(<AttestorApplicationPanel />);
    await waitFor(() =>
      expect(listMyAttestorApplications).toHaveBeenCalled(),
    );

    expect(
      screen.getByText(/Need a verifiable professional reference/i),
    ).toBeInTheDocument();
    // Rejected (not pending) → user may submit a fresh application.
    expect(
      screen.getByRole("button", { name: /submit application/i }),
    ).toBeInTheDocument();
  });
});
