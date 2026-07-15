import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { uploadOrgAttestorTaxDocument } from "@/lib/generated/sdk.gen";
import { TaxDocumentGate } from "./tax-document-gate";

vi.mock("@/lib/generated/sdk.gen", () => ({
  uploadOrgAttestorTaxDocument: vi.fn(),
}));

vi.mock("@/lib/auth/form-client", () => ({
  getAccessTokenHeaders: () => ({ Authorization: "Bearer test" }),
  describeGeneratedError: () => "error",
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
});
