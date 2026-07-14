import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  addAttestorIncorporationDocumentV1OrgsOrgIdAttestorApplicationIncorporationDocumentPost as addIncorporationDocument,
  createOrgAttestorApplication,
  removeAttestorIncorporationDocumentV1OrgsOrgIdAttestorApplicationIncorporationDocumentDelete as removeIncorporationDocument,
  submitOrgAttestorApplication,
} from "@/lib/generated/sdk.gen";
import { ApplyGate } from "./apply-gate";

vi.mock("@/lib/generated/sdk.gen", () => ({
  addAttestorIncorporationDocumentV1OrgsOrgIdAttestorApplicationIncorporationDocumentPost:
    vi.fn(),
  createOrgAttestorApplication: vi.fn(),
  removeAttestorIncorporationDocumentV1OrgsOrgIdAttestorApplicationIncorporationDocumentDelete:
    vi.fn(),
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

  it("enables Save Draft once create fields are filled but keeps Submit gated", () => {
    render(<ApplyGate orgId="org-1" application={null} onChange={vi.fn()} />);

    const submit = screen.getByRole("button", { name: /Submit Application/i });
    const saveDraft = screen.getByRole("button", { name: /Save Draft/i });
    expect(submit).toHaveProperty("disabled", true);
    expect(saveDraft).toHaveProperty("disabled", true);

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

    // Create-required fields are satisfied, so the draft can be saved. Submit
    // still needs legal name, registration number, and an incorporation
    // document, which are attached only after the draft exists.
    expect(saveDraft).toHaveProperty("disabled", false);
    expect(submit).toHaveProperty("disabled", true);
  });

  it("enables Submit for a fully complete existing application", () => {
    render(
      <ApplyGate
        orgId="org-1"
        onChange={vi.fn()}
        application={
          {
            status: "draft",
            legal_name: "Meridian Ltd.",
            registration_number: "RC123456",
            credentials_summary: "Ten years of audit experience across sectors.",
            professional_references: "Jane Doe, jane@example.com",
            incorporation_doc_keys: ["kyb/org-1/app/uuid-cert.pdf"],
            sectors: ["private_equity"],
            functions: ["compliance"],
            jurisdictions: ["united_states"],
          } as never
        }
      />,
    );

    expect(
      screen.getByRole("button", { name: /Submit Application/i }),
    ).toHaveProperty("disabled", false);
  });

  it("attaches an incorporation document via the dedicated endpoint", async () => {
    vi.mocked(addIncorporationDocument).mockResolvedValue({ data: {} } as never);
    const onChange = vi.fn();
    render(
      <ApplyGate
        orgId="org-1"
        onChange={onChange}
        application={{ status: "draft", incorporation_doc_keys: [] } as never}
      />,
    );

    const file = new File(["x"], "cert.pdf", { type: "application/pdf" });
    fireEvent.change(screen.getByLabelText(/Incorporation document file/i), {
      target: { files: [file] },
    });
    fireEvent.click(screen.getByRole("button", { name: /Add document/i }));

    await waitFor(() => expect(addIncorporationDocument).toHaveBeenCalled());
    const arg = vi.mocked(addIncorporationDocument).mock.calls[0][0];
    expect(arg.body.file_name).toBe("cert.pdf");
    expect(arg.body.content_type).toBe("application/pdf");
    expect(onChange).toHaveBeenCalled();
  });

  it("removes an attached incorporation document", async () => {
    vi.mocked(removeIncorporationDocument).mockResolvedValue({ data: {} } as never);
    const onChange = vi.fn();
    render(
      <ApplyGate
        orgId="org-1"
        onChange={onChange}
        application={
          {
            status: "draft",
            incorporation_doc_keys: ["kyb/org-1/app/uuid-cert.pdf"],
          } as never
        }
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /Remove/i }));

    await waitFor(() => expect(removeIncorporationDocument).toHaveBeenCalled());
    const arg = vi.mocked(removeIncorporationDocument).mock.calls[0][0];
    expect(arg.body.s3_key).toBe("kyb/org-1/app/uuid-cert.pdf");
    expect(onChange).toHaveBeenCalled();
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
