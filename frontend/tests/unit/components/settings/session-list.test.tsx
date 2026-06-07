import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SessionList } from "@/components/modules/settings/session-list";
import { revokeSession } from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  getAccessTokenHeaders: () => ({ Authorization: "Bearer access-token" }),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  revokeOtherSessions: vi.fn(),
  revokeSession: vi.fn(),
}));

describe("SessionList", () => {
  beforeEach(() => {
    vi.mocked(revokeSession).mockReset();
  });

  it("revokes a selected browser session through the generated client", async () => {
    vi.mocked(revokeSession).mockResolvedValue({
      data: { message: "Session revoked." },
      error: undefined,
      response: new Response(null, { status: 200 }),
    });

    render(
      <SessionList
        initialSessions={[
          {
            created_at: "2026-06-07T10:00:00Z",
            current: true,
            id: "current-session",
            ip: "127.0.0.1",
            last_seen: "2026-06-07T10:05:00Z",
            user_agent: "Safari",
          },
        ]}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /revoke session/i }));

    await waitFor(() => {
      expect(revokeSession).toHaveBeenCalledWith({
        headers: { Authorization: "Bearer access-token" },
        path: { session_id: "current-session" },
      });
    });
    expect(await screen.findByText(/session revoked/i)).toBeInTheDocument();
  });
});
