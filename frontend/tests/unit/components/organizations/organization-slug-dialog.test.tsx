/**
 * Organization slug change dialog.
 *
 * Confirm stays disabled until the new slug obeys the creation rules and
 * differs from the current one; a conflict is explained under the field; a
 * success sends `{slug}`, refreshes the organization, and closes.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { OrganizationSlugDialog } from "@/components/modules/organizations/organization-slug-dialog";
import { useOrganization } from "@/components/modules/organizations/organization-context";
import { configureBrowserClient } from "@/lib/auth/form-client";
import { changeOrgSlugV1OrgsOrgIdSlugPatch } from "@/lib/generated/sdk.gen";

const success = vi.fn();
const refreshOrganization = vi.fn().mockResolvedValue(undefined);

vi.mock("@/components/modules/organizations/organization-context", () => ({
  useOrganization: vi.fn(),
}));
vi.mock("@/components/ui/toast", () => ({
  useToast: () => ({ success, error: vi.fn() }),
}));
vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: vi.fn((error: { detail?: string }) => error?.detail ?? "error"),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer t" })),
}));
vi.mock("@/lib/generated/sdk.gen", () => ({ changeOrgSlugV1OrgsOrgIdSlugPatch: vi.fn() }));

function renderDialog(onClose = vi.fn()) {
  render(<OrganizationSlugDialog onClose={onClose} open />);
  return { onClose, input: screen.getByLabelText("New address") as HTMLInputElement };
}

function confirmButton() {
  return screen.getByRole("button", { name: "Change address" });
}

describe("OrganizationSlugDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(useOrganization).mockReturnValue({
      orgId: "org-1",
      org: { slug: "meridian" },
      refreshOrganization,
    } as never);
  });

  it("prefills the current slug, shows the rule and the redirect warning", () => {
    const { input } = renderDialog();

    expect(input.value).toBe("meridian");
    expect(screen.getByText(/3–80 characters/)).toBeInTheDocument();
    expect(
      screen.getByText("Your current link /orgs/meridian will keep working and redirect here."),
    ).toBeInTheDocument();
    expect(confirmButton()).toBeDisabled();
  });

  it("previews the new public URL as the owner types", () => {
    const { input } = renderDialog();
    fireEvent.change(input, { target: { value: "Meridian-NG" } });

    expect(input.value).toBe("meridian-ng");
    expect(screen.getByTestId("slug-preview")).toHaveTextContent("/orgs/meridian-ng");
    expect(confirmButton()).toBeEnabled();
  });

  it.each(["ab", "bad slug", "under_score", "a".repeat(81)])(
    "keeps confirm disabled for the invalid slug %s",
    (value) => {
      const { input } = renderDialog();
      fireEvent.change(input, { target: { value } });
      expect(confirmButton()).toBeDisabled();
    },
  );

  it("shows the conflict message under the field on 409", async () => {
    vi.mocked(changeOrgSlugV1OrgsOrgIdSlugPatch).mockResolvedValue({
      data: undefined,
      error: { detail: "That address is already taken." },
      response: new Response(null, { status: 409 }),
    } as never);
    const { input, onClose } = renderDialog();
    fireEvent.change(input, { target: { value: "taken-slug" } });
    fireEvent.click(confirmButton());

    expect(await screen.findByText("That address is already taken.")).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
    expect(refreshOrganization).not.toHaveBeenCalled();
  });

  it("sends the slug, refreshes the organization, toasts, and closes on success", async () => {
    vi.mocked(changeOrgSlugV1OrgsOrgIdSlugPatch).mockResolvedValue({
      data: { id: "org-1", slug: "meridian-ng" },
      error: undefined,
      response: new Response(null, { status: 200 }),
    } as never);
    const { input, onClose } = renderDialog();
    fireEvent.change(input, { target: { value: "meridian-ng" } });
    fireEvent.click(confirmButton());

    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(configureBrowserClient).toHaveBeenCalled();
    expect(changeOrgSlugV1OrgsOrgIdSlugPatch).toHaveBeenCalledWith(
      expect.objectContaining({ body: { slug: "meridian-ng" }, path: { org_id: "org-1" } }),
    );
    expect(refreshOrganization).toHaveBeenCalled();
    expect(success).toHaveBeenCalledWith("Public address updated.");
  });
});
