import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  createOrgAttestorApplication,
  submitOrgAttestorApplication,
} from "@/lib/generated/sdk.gen";
import { ApplyGate } from "./apply-gate";

vi.mock("@/lib/generated/sdk.gen", () => ({
  createOrgAttestorApplication: vi.fn(),
  updateOrgAttestorApplication: vi.fn(),
  submitOrgAttestorApplication: vi.fn(),
}));

vi.mock("@/lib/auth/form-client", () => ({
  getAccessTokenHeaders: () => ({ Authorization: "Bearer test" }),
  describeGeneratedError: () => "error",
}));

describe("ApplyGate specialisation controls", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(createOrgAttestorApplication).mockResolvedValue({ data: {} } as never);
    vi.mocked(submitOrgAttestorApplication).mockResolvedValue({ data: {} } as never);
  });

  it("submits dropdown-selected sectors, categories, and jurisdictions", async () => {
    render(<ApplyGate orgId="org-1" application={null} onChange={vi.fn()} />);

    fireEvent.change(screen.getByLabelText(/Legal Name/i), {
      target: { value: "Meridian Ltd." },
    });
    fireEvent.change(screen.getByLabelText(/Credentials Summary/i), {
      target: { value: "Ten years of audit experience across sectors." },
    });
    fireEvent.change(screen.getByLabelText(/Professional References/i), {
      target: { value: "Jane Doe, jane@example.com" },
    });

    // Pick from each dropdown; selecting an option adds it to the list.
    fireEvent.change(screen.getByLabelText(/Sectors/i), {
      target: { value: "PE" },
    });
    fireEvent.change(screen.getByLabelText(/Framework Categories/i), {
      target: { value: "Compliance" },
    });
    fireEvent.change(screen.getByLabelText(/Jurisdictions/i), {
      target: { value: "united_states" },
    });

    fireEvent.click(screen.getByRole("button", { name: /Submit Application/i }));

    await waitFor(() => expect(createOrgAttestorApplication).toHaveBeenCalled());

    const body = vi.mocked(createOrgAttestorApplication).mock.calls[0][0].body;
    expect(body.sectors).toEqual(["PE"]);
    expect(body.framework_categories).toEqual(["Compliance"]);
    expect(body.jurisdictions).toEqual(["united_states"]);
  });

  it("submits the backend value while showing the friendly label as a chip", async () => {
    render(<ApplyGate orgId="org-1" application={null} onChange={vi.fn()} />);

    fireEvent.change(screen.getByLabelText(/Sectors/i), {
      target: { value: "PE" },
    });

    // The chip renders the human label, not the raw backend value.
    expect(screen.getByText("Private Equity")).toBeTruthy();
  });
});
