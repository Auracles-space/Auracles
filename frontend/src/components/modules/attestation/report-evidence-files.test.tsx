import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { listAttestationEvidenceFiles } from "@/lib/generated/sdk.gen";
import { ReportEvidenceFiles } from "./report-evidence-files";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  getAccessTokenHeaders: () => ({ Authorization: "Bearer test" }),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  listAttestationEvidenceFiles: vi.fn(),
}));

describe("ReportEvidenceFiles", () => {
  it("links clean evidence files and marks ones still being scanned", async () => {
    vi.mocked(listAttestationEvidenceFiles).mockResolvedValue({
      response: { ok: true },
      data: {
        files: [
          { file_name: "cac.pdf", scan_status: "clean", download_url: "https://s3.test/cac?sig=1" },
          { file_name: "bank.pdf", scan_status: "pending_scan", download_url: null },
        ],
      },
    } as never);

    render(<ReportEvidenceFiles attestationId="att-1" />);

    const link = await screen.findByRole("link", { name: /cac\.pdf/ });
    expect(link).toHaveAttribute("href", "https://s3.test/cac?sig=1");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    expect(screen.getByText("bank.pdf")).toBeInTheDocument();
    expect(screen.getByText(/being scanned/i)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /bank\.pdf/ })).toBeNull();
    expect(listAttestationEvidenceFiles).toHaveBeenCalledWith(
      expect.objectContaining({ path: { attestation_id: "att-1" } }),
    );
  });

  it("renders nothing when the report has no evidence files", async () => {
    vi.mocked(listAttestationEvidenceFiles).mockResolvedValue({
      response: { ok: true },
      data: { files: [] },
    } as never);

    const { container } = render(<ReportEvidenceFiles attestationId="att-1" />);

    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(container).toBeEmptyDOMElement();
  });
});
