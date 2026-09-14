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

vi.mock("@/components/modules/organizations/organization-context", () => ({
  useOrganization: () => ({ orgId: "org-1" }),
}));

describe("TaxDocumentGate", () => {
  beforeEach(() => vi.clearAllMocks());

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

    expect(screen.getByText(/already on file/i)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Upload Document/i }),
    ).toBeInTheDocument();
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
