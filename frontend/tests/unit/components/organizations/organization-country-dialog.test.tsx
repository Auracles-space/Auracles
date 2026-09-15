/**
 * Organization country change dialog.
 *
 * Prefills the current country, keeps confirm disabled until a different
 * country is picked, explains the lock under the field on 409, and on success
 * sends `{country}`, refreshes the organization, and closes.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { OrganizationCountryDialog } from "@/components/modules/organizations/organization-country-dialog";
import { useOrganization } from "@/components/modules/organizations/organization-context";
import { changeOrgCountryV1OrgsOrgIdCountryPatch } from "@/lib/generated/sdk.gen";

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
  describeGeneratedError: vi.fn(
    (error: { detail?: { message?: string } }) => error?.detail?.message ?? "error",
  ),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer t" })),
}));
vi.mock("@/lib/generated/sdk.gen", () => ({ changeOrgCountryV1OrgsOrgIdCountryPatch: vi.fn() }));

function renderDialog(onClose = vi.fn()) {
  render(<OrganizationCountryDialog onClose={onClose} open />);
  return { onClose, select: screen.getByLabelText("Country") as HTMLSelectElement };
}

const confirmButton = () => screen.getByRole("button", { name: "Change country" });

describe("OrganizationCountryDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(useOrganization).mockReturnValue({
      orgId: "org-1",
      org: { country: "GB" },
      refreshOrganization,
    } as never);
  });

  it("prefills the current country, explains the rail, and starts disabled", () => {
    const { select } = renderDialog();

    expect(select.value).toBe("GB");
    expect(screen.getByText(/Nigeria settles on Paystack/)).toBeInTheDocument();
    expect(confirmButton()).toBeDisabled();
  });

  it("sends the new country, refreshes, and closes on success", async () => {
    vi.mocked(changeOrgCountryV1OrgsOrgIdCountryPatch).mockResolvedValue({
      data: {},
      error: undefined,
      response: new Response(null, { status: 200 }),
    } as never);
    const { select, onClose } = renderDialog();

    fireEvent.change(select, { target: { value: "NG" } });
    fireEvent.click(confirmButton());

    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(changeOrgCountryV1OrgsOrgIdCountryPatch).toHaveBeenCalledWith(
      expect.objectContaining({ body: { country: "NG" }, path: { org_id: "org-1" } }),
    );
    expect(refreshOrganization).toHaveBeenCalled();
    expect(success).toHaveBeenCalledWith("Country updated.");
  });

  it("shows the lock reason under the field on 409", async () => {
    vi.mocked(changeOrgCountryV1OrgsOrgIdCountryPatch).mockResolvedValue({
      data: undefined,
      error: {
        detail: {
          error_code: "org_country_locked",
          message: "The country can't change once a payout account is connected.",
        },
      },
      response: new Response(null, { status: 409 }),
    } as never);
    const { select, onClose } = renderDialog();

    fireEvent.change(select, { target: { value: "NG" } });
    fireEvent.click(confirmButton());

    expect(
      await screen.findByText("The country can't change once a payout account is connected."),
    ).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
  });
});
