import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CreateFrameworkPanel } from "@/components/modules/frameworks/create-framework-panel";
import type { FrameworkCreate } from "@/lib/generated/types.gen";

const push = vi.fn();
const createFramework = vi.fn();

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

vi.mock("@/lib/frameworks/framework-api", () => ({
  frameworkApiFor: vi.fn(() => ({ create: createFramework })),
}));

vi.mock("@/lib/auth/token-store", () => ({
  authTokenStore: {
    getState: () => ({ accessToken: "access-token" }),
  },
}));

describe("CreateFrameworkPanel", () => {
  beforeEach(() => {
    push.mockReset();
    createFramework.mockReset();
  });

  it("redirects to the draft workspace when a Framework is created", async () => {
    createFramework.mockResolvedValue({
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
    });

    render(
      <CreateFrameworkPanel
        seller={{ kind: "org", orgId: "org-1" }}
        basePath="/dashboard/organizations/org-1/frameworks"
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /submit framework/i }));

    await waitFor(() => {
      expect(push).toHaveBeenCalledWith(
        "/dashboard/organizations/org-1/frameworks/fw_123",
      );
    });
    expect(createFramework).toHaveBeenCalled();
  });
});
