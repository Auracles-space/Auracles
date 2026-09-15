import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { uploadOrgAttestorTaxDocument } from "@/lib/generated/sdk.gen";
import { configureBrowserClient } from "@/lib/auth/form-client";
import { TaxDocumentGate } from "./tax-document-gate";

vi.mock("@/lib/generated/sdk.gen", () => ({
  uploadOrgAttestorTaxDocument: vi.fn(),
}));

// Keep the real describeGeneratedError so surfaced copy is what users read;
// configureBrowserClient touches the (mocked-away) transport client.
vi.mock("@/lib/auth/form-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/auth/form-client")>()),
  configureBrowserClient: vi.fn(),
  getAccessTokenHeaders: () => ({ Authorization: "Bearer test" }),
}));

const orgState = vi.hoisted(() => ({ country: "US" }));

vi.mock("@/components/modules/organizations/organization-context", () => ({
  useOrganization: () => ({ orgId: "org-1", org: { country: orgState.country } }),
}));

describe("TaxDocumentGate", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    orgState.country = "US";
  });

  it("uploads the tax document to S3 after reserving the key", async () => {
    // Reserving the key is not enough: without the S3 POST, the admin download
    // later resolves to a missing object (NoSuchKey).
    vi.mocked(uploadOrgAttestorTaxDocument).mockResolvedValue({
      data: {
        s3_key: "org-attestor-tax-documents/org-1/app/uuid-w9.pdf",
        url: "https://bucket.s3.amazonaws.com/",
        fields: { key: "org-attestor-tax-documents/org-1/app/uuid-w9.pdf" },
      },
    } as never);
    const fetchMock = vi.fn().mockResolvedValue({ ok: true } as Response);
    vi.stubGlobal("fetch", fetchMock);
    const onChange = vi.fn();

    render(<TaxDocumentGate application={null} onChange={onChange} />);

    const file = new File(["x"], "w9.pdf", { type: "application/pdf" });
    fireEvent.change(screen.getByLabelText(/Upload Document/i), {
      target: { files: [file] },
    });
    fireEvent.click(screen.getByRole("button", { name: /Upload Document/i }));

    await waitFor(() => expect(uploadOrgAttestorTaxDocument).toHaveBeenCalled());
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("https://bucket.s3.amazonaws.com/");
    expect(init.method).toBe("POST");
    expect((init.body as FormData).get("file")).toBeInstanceOf(File);
    expect(onChange).toHaveBeenCalled();
    vi.unstubAllGlobals();
  });

  it("allows replacing the tax document while the application needs info", () => {
    // A dangling or superseded document must be replaceable, or a needs-info
    // application can never fix its tax document.
    render(
      <TaxDocumentGate
        application={
          { status: "needs_info", tax_document_key: "org-tax/old.pdf" } as never
        }
        onChange={vi.fn()}
      />,
    );

    expect(screen.getByText("Tax document on file")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Replace document" }));
    expect(screen.getByText(/Uploading a new one replaces it/i)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Upload Document/i }),
    ).toBeInTheDocument();
  });

  it("shows the saved document, not an empty form, when the owner returns to the step", () => {
    // The stepper remounts the gate on every visit, so the confirmation must
    // come from the application, not from state set during the upload.
    render(
      <TaxDocumentGate
        application={
          { status: "draft", tax_document_key: "org-tax/w9.pdf", tax_document_type: "other" } as never
        }
        onChange={vi.fn()}
      />,
    );

    expect(screen.getByText("Tax document on file")).toBeInTheDocument();
    expect(screen.getByText(/Other \/ Exemption/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Upload Document/i })).toBeNull();
  });

  it("locks the tax document once the application is submitted", () => {
    render(
      <TaxDocumentGate
        application={
          { status: "submitted", tax_document_key: "org-tax/final.pdf" } as never
        }
        onChange={vi.fn()}
      />,
    );

    expect(screen.getByText(/uploaded successfully/i)).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Upload Document/i }),
    ).not.toBeInTheDocument();
  });

  it("surfaces an error and does not confirm when the S3 upload fails", async () => {
    vi.mocked(uploadOrgAttestorTaxDocument).mockResolvedValue({
      data: {
        s3_key: "org-attestor-tax-documents/org-1/app/uuid-w9.pdf",
        url: "https://bucket.s3.amazonaws.com/",
        fields: {},
      },
    } as never);
    const fetchMock = vi.fn().mockResolvedValue({ ok: false } as Response);
    vi.stubGlobal("fetch", fetchMock);
    const onChange = vi.fn();

    render(<TaxDocumentGate application={null} onChange={onChange} />);

    const file = new File(["x"], "w9.pdf", { type: "application/pdf" });
    fireEvent.change(screen.getByLabelText(/Upload Document/i), {
      target: { files: [file] },
    });
    fireEvent.click(screen.getByRole("button", { name: /Upload Document/i }));

    await waitFor(() =>
      expect(screen.getByText(/could not be completed/i)).toBeInTheDocument(),
    );
    expect(onChange).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });

  /** Select a file and submit the form. */
  function submitFile() {
    const file = new File(["x"], "w9.pdf", { type: "application/pdf" });
    fireEvent.change(screen.getByLabelText(/Upload Document/i), {
      target: { files: [file] },
    });
    fireEvent.click(screen.getByRole("button", { name: /Upload Document/i }));
  }

  it("installs the browser client before reserving and surfaces a 403 message", async () => {
    vi.mocked(uploadOrgAttestorTaxDocument).mockResolvedValue({
      data: undefined,
      error: { detail: "Tax documents are locked once the application is submitted." },
      response: { ok: false, status: 403 },
    } as never);
    const onChange = vi.fn();

    render(<TaxDocumentGate application={null} onChange={onChange} />);
    submitFile();

    expect(
      await screen.findByText(
        "Tax documents are locked once the application is submitted.",
      ),
    ).toBeInTheDocument();
    expect(configureBrowserClient).toHaveBeenCalled();
    expect(onChange).not.toHaveBeenCalled();
  });

  it("describes a thrown failure instead of a generic unexpected-error line", async () => {
    vi.mocked(uploadOrgAttestorTaxDocument).mockRejectedValue({
      detail: "Upload service is unavailable.",
    });

    render(<TaxDocumentGate application={null} onChange={vi.fn()} />);
    submitFile();

    expect(await screen.findByText("Upload service is unavailable.")).toBeInTheDocument();
    expect(screen.queryByText("An unexpected error occurred.")).not.toBeInTheDocument();
  });
});

describe("TaxDocumentGate document types by country", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    orgState.country = "US";
  });

  function optionLabels() {
    const select = screen.getByLabelText(/Document type/i) as HTMLSelectElement;
    return Array.from(select.options).map((option) => option.textContent);
  }

  it("offers Nigerian tax documents, not US IRS forms, to a Nigerian org", () => {
    orgState.country = "NG";
    render(<TaxDocumentGate application={null} onChange={vi.fn()} />);

    expect(optionLabels()).toEqual([
      "FIRS TIN certificate",
      "Tax Clearance Certificate (TCC)",
      "Other / Exemption",
    ]);
  });

  it("offers US IRS forms, not Nigerian documents, elsewhere", () => {
    render(<TaxDocumentGate application={null} onChange={vi.fn()} />);

    expect(optionLabels()).toEqual([
      "W-9 (US Persons)",
      "W-8BEN (Non-US Persons)",
      "Other / Exemption",
    ]);
  });

  it("uploads a Nigerian org's default choice as a FIRS TIN certificate", async () => {
    orgState.country = "NG";
    vi.mocked(uploadOrgAttestorTaxDocument).mockResolvedValue({
      error: { detail: "stop" },
    } as never);
    render(<TaxDocumentGate application={null} onChange={vi.fn()} />);

    fireEvent.change(screen.getByLabelText(/Upload Document/i), {
      target: { files: [new File(["x"], "tin.pdf", { type: "application/pdf" })] },
    });
    fireEvent.click(screen.getByRole("button", { name: /Upload Document/i }));

    await waitFor(() => expect(uploadOrgAttestorTaxDocument).toHaveBeenCalled());
    expect(vi.mocked(uploadOrgAttestorTaxDocument).mock.calls[0][0].body.tax_document_type).toBe(
      "firs_tin",
    );
  });

  it("names a stored Nigerian document on the on-file card", () => {
    orgState.country = "NG";
    render(
      <TaxDocumentGate
        application={
          {
            status: "draft",
            tax_document_key: "org-attestor-tax-documents/org-1/app/tcc.pdf",
            tax_document_type: "tcc",
          } as never
        }
        onChange={vi.fn()}
      />,
    );

    expect(screen.getByText("Tax Clearance Certificate (TCC)")).toBeInTheDocument();
  });
});
