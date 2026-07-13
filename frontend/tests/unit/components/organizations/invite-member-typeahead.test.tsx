import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { InviteMemberTypeahead } from "@/components/modules/organizations/invite-member-typeahead";
import { searchOrgMembers } from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer test-token" })),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  searchOrgMembers: vi.fn(),
}));

describe("InviteMemberTypeahead", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useRealTimers();
  });

  it("shows masked suggestions after 3 chars and emits user_id on select", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.mocked(searchOrgMembers).mockResolvedValue({
      data: {
        results: [
          {
            user_id: "user-1",
            display_name: "Joanna Reed",
            avatar_url: null,
            masked_email: "j•••@example.com",
          },
        ],
      },
      error: undefined,
      request: new Request("http://test.local"),
      response: new Response(null, { status: 200 }),
    } as never);

    const onSelect = vi.fn();
    const onEmailChange = vi.fn();

    render(
      <InviteMemberTypeahead
        orgId="org-1"
        value=""
        onSelect={onSelect}
        onEmailChange={onEmailChange}
      />,
    );

    fireEvent.change(screen.getByLabelText(/invite by email/i), {
      target: { value: "joa" },
    });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(250);
    });

    await waitFor(() => {
      expect(screen.getByText("Joanna Reed")).toBeInTheDocument();
    });
    expect(screen.getByText("j•••@example.com")).toBeInTheDocument();

    fireEvent.click(screen.getByText("Joanna Reed"));

    expect(onSelect).toHaveBeenCalledWith("user-1");
    vi.useRealTimers();
  });

  it("does not search below 3 chars", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });

    render(
      <InviteMemberTypeahead
        orgId="org-1"
        value=""
        onSelect={vi.fn()}
        onEmailChange={vi.fn()}
      />,
    );

    fireEvent.change(screen.getByLabelText(/invite by email/i), {
      target: { value: "jo" },
    });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
    });

    expect(searchOrgMembers).not.toHaveBeenCalled();
    vi.useRealTimers();
  });
});
