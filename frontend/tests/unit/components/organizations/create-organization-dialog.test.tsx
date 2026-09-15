import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CreateOrganizationDialog } from "@/components/modules/organizations/create-organization-dialog";
import { createOrganizationV1OrgsPost } from "@/lib/generated/sdk.gen";

const push = vi.fn();

vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("@/lib/auth/form-client", () => ({
  describeGeneratedError: vi.fn(
    (error: { detail?: { message?: string } } | undefined) =>
      error?.detail?.message ?? "The request could not be completed.",
  ),
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
  // Submit label is "Create Organization" or "Create & continue" (attestor intent).
  fireEvent.click(screen.getByRole("button", { name: /^Create (Organization|& continue)$/i }));
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

  it("frames the dialog as the attestor path when redirectIntent is attestor", async () => {
    render(<CreateOrganizationDialog open onClose={() => {}} redirectIntent="attestor" />);

    expect(await screen.findByText(/Create your attesting organization/i)).toBeInTheDocument();
    expect(screen.getByText(/complete the attestor application/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Create & continue/i })).toBeInTheDocument();
  });

  it("uses the plain title and button without redirectIntent", async () => {
    render(<CreateOrganizationDialog open onClose={() => {}} />);

    expect(await screen.findByRole("heading", { name: /^Create Organization$/i })).toBeInTheDocument();
    expect(screen.queryByText(/attesting organization/i)).not.toBeInTheDocument();
  });

  it("offers the full Stripe Connect country list", async () => {
    render(<CreateOrganizationDialog open onClose={() => {}} />);

    const country = (await screen.findByLabelText(/Country/i)) as HTMLSelectElement;
    // Beyond the original 7-country stub — e.g. Japan must now be selectable.
    expect(
      screen.getByRole("option", { name: "Japan" }),
    ).toBeInTheDocument();
    fireEvent.change(country, { target: { value: "JP" } });
    expect(country.value).toBe("JP");
  });
});

describe("CreateOrganizationDialog slug preview and server errors", () => {
  beforeEach(() => vi.clearAllMocks());

  it("previews the public URL live as the slug is typed", async () => {
    render(<CreateOrganizationDialog open onClose={() => {}} />);

    const preview = await screen.findByTestId("slug-preview");
    expect(preview).toHaveTextContent(`${window.location.origin}/orgs/`);

    fireEvent.change(screen.getByLabelText(/Slug/i), {
      target: { value: "Meridian-Audit" },
    });

    // The slug is lower-cased on input, so the preview shows the real URL.
    expect(preview).toHaveTextContent(`${window.location.origin}/orgs/meridian-audit`);
  });

  it("explains that the country picks the payout rail and locks at verification", () => {
    render(<CreateOrganizationDialog open onClose={() => {}} />);

    expect(
      screen.getByText(/country picks the payout rail and locks once business verification/i),
    ).toBeInTheDocument();
  });

  it("defaults the country to Nigeria, the pilot market", async () => {
    render(<CreateOrganizationDialog open onClose={() => {}} />);

    const country = (await screen.findByLabelText(/Country/i)) as HTMLSelectElement;
    expect(country.value).toBe("NG");
  });

  it("shows the server message on a slug conflict instead of a raw code", async () => {
    vi.mocked(createOrganizationV1OrgsPost).mockResolvedValue({
      data: undefined,
      error: { detail: { error_code: "slug_taken", message: "That slug is already in use." } },
      request: new Request("http://t"),
      response: new Response(null, { status: 409 }),
    } as never);

    render(<CreateOrganizationDialog open onClose={() => {}} />);
    await fillAndSubmit();

    expect(await screen.findByText("That slug is already in use.")).toBeInTheDocument();
    expect(screen.queryByText("slug_taken")).toBeNull();
    expect(push).not.toHaveBeenCalled();
  });

  it("shows the server message for any other failure", async () => {
    vi.mocked(createOrganizationV1OrgsPost).mockResolvedValue({
      data: undefined,
      error: { detail: { error_code: "step_up_required", message: "Confirm your identity first." } },
      request: new Request("http://t"),
      response: new Response(null, { status: 403 }),
    } as never);

    render(<CreateOrganizationDialog open onClose={() => {}} />);
    await fillAndSubmit();

    expect(await screen.findByText("Confirm your identity first.")).toBeInTheDocument();
    expect(screen.queryByText("step_up_required")).toBeNull();
  });
});
