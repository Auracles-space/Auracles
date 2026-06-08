import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CreateFrameworkPanel } from "@/components/modules/frameworks/create-framework-panel";
import { createFramework } from "@/lib/generated/sdk.gen";
import type { FrameworkCreate } from "@/lib/generated/types.gen";

const push = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}));

vi.mock("@/components/modules/frameworks/framework-form", () => ({
  FrameworkForm: ({
    onSubmit,
  }: {
    onSubmit: (payload: FrameworkCreate) => Promise<void>;
  }) => (
    <button
      onClick={() =>
        onSubmit({
          category: "toolkit",
          description: "A clean operating framework.",
          pricing: {
            currency: "USD",
            license_types: ["single_user"],
            price: "250.00",
          },
          tags: ["operations"],
          title: "Operating Framework",
        })
      }
      type="button"
    >
      Submit framework
    </button>
  ),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  client: {
    interceptors: { response: { use: vi.fn() } },
    setConfig: vi.fn(),
  },
  createFramework: vi.fn(),
}));

vi.mock("@/lib/auth/token-store", () => ({
  authTokenStore: {
    getState: () => ({ accessToken: "access-token" }),
  },
}));

describe("CreateFrameworkPanel", () => {
  beforeEach(() => {
    push.mockReset();
    vi.mocked(createFramework).mockReset();
  });

  it("redirects to the draft workspace when a Framework is created", async () => {
    vi.mocked(createFramework).mockResolvedValue({
      data: {
        artifacts: [],
        category: "toolkit",
        contributor_id: "user_123",
        created_at: "2026-06-08T10:00:00Z",
        current_version: 1,
        description: "A clean operating framework.",
        id: "fw_123",
        pricing: {
          currency: "USD",
          license_types: ["single_user"],
          price: "250.00",
        },
        processing_state: "draft",
        published_at: null,
        review_status: null,
        status: "draft",
        tags: ["operations"],
        title: "Operating Framework",
        updated_at: "2026-06-08T10:00:00Z",
      },
      error: undefined,
      response: new Response(null, { status: 201 }),
    });

    render(<CreateFrameworkPanel />);

    fireEvent.click(screen.getByRole("button", { name: /submit framework/i }));

    await waitFor(() => {
      expect(push).toHaveBeenCalledWith("/dashboard/frameworks/fw_123");
    });
  });
});
