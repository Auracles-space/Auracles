import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  createOrgAttestorApplication,
} from "@/lib/generated/sdk.gen";
import { ApplyGate } from "./apply-gate";

vi.mock("@/lib/generated/sdk.gen", () => ({
  addAttestorIncorporationDocumentV1OrgsOrgIdAttestorApplicationIncorporationDocumentPost:
    vi.fn(),
  createOrgAttestorApplication: vi.fn(),
  removeAttestorIncorporationDocumentV1OrgsOrgIdAttestorApplicationIncorporationDocumentDelete:
    vi.fn(),
  updateOrgAttestorApplication: vi.fn(),
}));

vi.mock("@/lib/auth/form-client", () => ({
  getAccessTokenHeaders: () => ({ Authorization: "Bearer test" }),
  describeGeneratedError: () => "error",
}));

describe("ApplyGate specialisation controls", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(createOrgAttestorApplication).mockResolvedValue({ data: {} } as never);
  });

  it("sends dropdown-selected sectors, functions, and jurisdictions on save", async () => {
    render(<ApplyGate orgId="org-1" application={null} onChange={vi.fn()} />);

    fireEvent.change(screen.getByLabelText(/Credentials Summary/i), {
      target: { value: "Ten years of audit experience across sectors." },
    });
    fireEvent.change(screen.getByLabelText(/Professional References/i), {
      target: { value: "Jane Doe, jane@example.com" },
    });

    // Pick from each dropdown; selecting an option adds it to the list.
    fireEvent.change(screen.getByLabelText(/Sectors/i), {
      target: { value: "private_equity" },
    });
    fireEvent.change(screen.getByLabelText(/Functions/i), {
      target: { value: "compliance" },
    });
    fireEvent.change(screen.getByLabelText(/Jurisdictions/i), {
      target: { value: "united_states" },
    });

    // A brand-new application must be saved as a draft before documents can be
    // attached, so the create call rides Save Draft, not Submit.
    fireEvent.click(screen.getByRole("button", { name: /Save Draft/i }));

    await waitFor(() => expect(createOrgAttestorApplication).toHaveBeenCalled());

    const body = vi.mocked(createOrgAttestorApplication).mock.calls[0][0].body;
    expect(body.sectors).toEqual(["private_equity"]);
    expect(body.functions).toEqual(["compliance"]);
    expect(body.jurisdictions).toEqual(["united_states"]);
  });

  it("enables Save Draft once the create-required fields are filled", () => {
    // Submit itself lives in the application tab's sticky bar now; the gate
    // only owns Save Draft, which unlocks once the create endpoint's required
    // fields are satisfied.
    render(<ApplyGate orgId="org-1" application={null} onChange={vi.fn()} />);

    const saveDraft = screen.getByRole("button", { name: /Save Draft/i });
    expect(saveDraft).toHaveProperty("disabled", true);
    expect(
      screen.queryByRole("button", { name: /Submit/i }),
    ).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText(/Credentials Summary/i), {
      target: { value: "Ten years of audit experience across sectors." },
    });
    fireEvent.change(screen.getByLabelText(/Professional References/i), {
      target: { value: "Jane Doe, jane@example.com" },
    });
    fireEvent.change(screen.getByLabelText(/Sectors/i), {
      target: { value: "private_equity" },
    });
    fireEvent.change(screen.getByLabelText(/Functions/i), {
      target: { value: "compliance" },
    });
    fireEvent.change(screen.getByLabelText(/Jurisdictions/i), {
      target: { value: "united_states" },
    });

    expect(saveDraft).toHaveProperty("disabled", false);
  });

  it("submits the backend value while showing the friendly label as a chip", async () => {
    render(<ApplyGate orgId="org-1" application={null} onChange={vi.fn()} />);

    fireEvent.change(screen.getByLabelText(/Sectors/i), {
      target: { value: "private_equity" },
    });

    // The chip renders the human label, not the raw backend value.
    expect(screen.getByText("Private Equity")).toBeTruthy();
  });

  it("prevents pointer focus when removing a selected chip", () => {
    render(
      <ApplyGate
        orgId="org-1"
        onChange={vi.fn()}
        application={
          {
            status: "draft",
            sectors: ["private_equity"],
            functions: [],
            jurisdictions: [],
          } as never
        }
      />,
    );

    const remove = screen.getByRole("button", {
      name: /remove private equity/i,
    });
    expect(remove.className).toContain("appearance-none");
    const event = new MouseEvent("mousedown", {
      bubbles: true,
      cancelable: true,
    });

    expect(remove.dispatchEvent(event)).toBe(false);
    fireEvent.click(remove);
    expect(
      screen.queryByRole("button", { name: /remove private equity/i }),
    ).not.toBeInTheDocument();
  });
});
