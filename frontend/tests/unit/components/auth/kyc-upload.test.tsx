import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { KycUpload } from "@/components/modules/auth/kyc-upload";
import { requestKycUploadUrl } from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/token-store", () => ({
  authTokenStore: {
    getState: () => ({ accessToken: "access-token" }),
  },
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  client: {
    interceptors: { response: { use: vi.fn() } },
    setConfig: vi.fn(),
  },
  requestKycUploadUrl: vi.fn(),
  submitKycUpload: vi.fn(),
}));

describe("KycUpload", () => {
  beforeEach(() => {
    vi.mocked(requestKycUploadUrl).mockReset();
  });

  it("keeps the submit disabled until a document file is selected", () => {
    const { container } = render(<KycUpload />);

    const submit = screen.getByRole("button", { name: /submit document/i });
    expect(submit).toBeDisabled();

    const fileInput = container.querySelector(
      "#doc-upload",
    ) as HTMLInputElement;
    const file = new File(["id-bytes"], "passport.png", { type: "image/png" });
    fireEvent.change(fileInput, { target: { files: [file] } });

    expect(submit).toBeEnabled();
  });

  it("does not request an upload URL while no file is selected", () => {
    render(<KycUpload />);

    fireEvent.click(screen.getByRole("button", { name: /submit document/i }));

    expect(requestKycUploadUrl).not.toHaveBeenCalled();
  });
});
