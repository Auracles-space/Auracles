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

  it("requires a document file before requesting an upload URL", async () => {
    render(<KycUpload />);

    fireEvent.click(screen.getByRole("button", { name: /submit document/i }));

    expect(await screen.findByText(/choose a document/i)).toBeInTheDocument();
    expect(requestKycUploadUrl).not.toHaveBeenCalled();
  });
});
