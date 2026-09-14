import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { TaxDocumentGate } from "@/components/modules/organizations/attestor/tax-document-gate";
import { uploadOrgAttestorTaxDocument } from "@/lib/generated/sdk.gen";
import { useOrganization } from "@/components/modules/organizations/organization-context";

vi.mock("@/lib/generated/sdk.gen", () => ({
  uploadOrgAttestorTaxDocument: vi.fn(),
}));
vi.mock("@/components/modules/organizations/organization-context", () => ({
  useOrganization: vi.fn(),
}));
vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: (e: unknown) => (e as Error).message,
  getAccessTokenHeaders: () => ({ Authorization: "Bearer token" }),
}));

function ok(data: unknown) {
  return { data, error: undefined };
}

describe("TaxDocumentGate", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders uploaded message if already uploaded", () => {
    vi.mocked(useOrganization).mockReturnValue({ role: "owner", orgId: "org-1" } as unknown as ReturnType<typeof useOrganization>);
    render(
      <TaxDocumentGate
        application={{ tax_document_key: "doc-123" } as never}
        onChange={vi.fn()}
      />
    );
    expect(screen.getByText(/Tax document uploaded successfully/i)).toBeInTheDocument();
  });

  it("submits tax document", async () => {
    vi.mocked(useOrganization).mockReturnValue({ role: "owner", orgId: "org-1" } as unknown as ReturnType<typeof useOrganization>);
    vi.mocked(uploadOrgAttestorTaxDocument).mockResolvedValue(
      ok({
        s3_key: "org-attestor-tax-documents/org-1/app/uuid-w9.pdf",
        url: "https://bucket.s3.amazonaws.com/",
        fields: { key: "org-attestor-tax-documents/org-1/app/uuid-w9.pdf" },
      }) as never,
    );
    const fetchMock = vi.fn().mockResolvedValue({ ok: true } as Response);
    vi.stubGlobal("fetch", fetchMock);
    const onChange = vi.fn();
    
    render(<TaxDocumentGate application={null} onChange={onChange} />);
    
    const file = new File(["hello"], "hello.pdf", { type: "application/pdf" });
    const input = screen.getByLabelText(/Upload Document/i);
    
    fireEvent.change(input, { target: { files: [file] } });
    fireEvent.click(screen.getByRole("button", { name: /Upload Document/i }));
    
    await waitFor(() =>
      expect(vi.mocked(uploadOrgAttestorTaxDocument)).toHaveBeenCalledWith(
        expect.objectContaining({
          path: { org_id: "org-1" },
          body: {
            tax_document_type: "w9",
            file_name: "hello.pdf",
            content_type: "application/pdf",
            size_bytes: 5,
          },
        })
      )
    );
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(onChange).toHaveBeenCalled();
    vi.unstubAllGlobals();
  });

  it("shows a pointer cursor on the file upload trigger", () => {
    vi.mocked(useOrganization).mockReturnValue({ role: "owner", orgId: "org-1" } as unknown as ReturnType<typeof useOrganization>);

    render(<TaxDocumentGate application={null} onChange={vi.fn()} />);

    expect(screen.getByLabelText(/Upload Document/i).className).toContain(
      "file:cursor-pointer",
    );
  });
});
