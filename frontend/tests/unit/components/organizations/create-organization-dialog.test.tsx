import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CreateOrganizationDialog } from "@/components/modules/organizations/create-organization-dialog";
import { createOrganizationV1OrgsPost } from "@/lib/generated/sdk.gen";

const push = vi.fn();

vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("@/lib/auth/form-client", () => ({
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer t" })),
}));
vi.mock("@/lib/generated/sdk.gen", () => ({ createOrganizationV1OrgsPost: vi.fn() }));

const ok = <T,>(data: T) => ({
  data,
  error: undefined,
  request: new Request("http://t"),
  response: new Response(null, { status: 200 }),
});

async function fillAndSubmit() {
  fireEvent.change(screen.getByLabelText(/Organization Name/i), {
    target: { value: "Acme" },
  });
  fireEvent.change(screen.getByLabelText(/Slug/i), {
    target: { value: "acme" },
  });
  fireEvent.click(screen.getByRole("button", { name: /^Create Organization$/i }));
}

describe("CreateOrganizationDialog redirect intent", () => {
  beforeEach(() => vi.clearAllMocks());

  it("routes to the org attestor tab when redirectIntent is attestor", async () => {
    vi.mocked(createOrganizationV1OrgsPost).mockResolvedValue(ok({ id: "org-9" }) as never);

    render(
      <CreateOrganizationDialog
        open
        onClose={() => {}}
        redirectIntent="attestor"
      />,
    );

    await fillAndSubmit();

    await waitFor(() => {
      expect(push).toHaveBeenCalledWith("/dashboard/organizations/org-9/attestor");
    });
  });

  it("routes to the organization page by default", async () => {
    vi.mocked(createOrganizationV1OrgsPost).mockResolvedValue(ok({ id: "org-9" }) as never);

    render(<CreateOrganizationDialog open onClose={() => {}} />);

    await fillAndSubmit();

    await waitFor(() => {
      expect(push).toHaveBeenCalledWith("/dashboard/organizations/org-9");
    });
  });

  it("portals the modal to document.body so it escapes the app shell stacking context", async () => {
    render(<CreateOrganizationDialog open onClose={() => {}} />);

    const dialog = await screen.findByRole("dialog");
    expect(dialog.parentElement).toBe(document.body);
  });
});
