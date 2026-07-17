import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  listAttestationClarifications,
  createAttestationClarification,
} from "@/lib/generated/sdk.gen";
import { ClarificationsPanel } from "./clarifications-panel";

vi.mock("@/lib/generated/sdk.gen", () => ({
  listAttestationClarifications: vi.fn(),
  createAttestationClarification: vi.fn(),
  markClarificationsSeen: vi.fn(),
}));

vi.mock("@/lib/auth/form-client", async (importActual) => ({
  ...(await importActual<typeof import("@/lib/auth/form-client")>()),
  getAccessTokenHeaders: () => ({ Authorization: "Bearer member" }),
}));

describe("ClarificationsPanel error handling", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(listAttestationClarifications).mockResolvedValue({
      response: { ok: true },
      data: [],
    } as never);
  });

  it("shows the backend error inline when asking a clarification fails", async () => {
    const alertSpy = vi.fn();
    vi.stubGlobal("alert", alertSpy);
    vi.mocked(createAttestationClarification).mockResolvedValue({
      data: undefined,
      error: { detail: "Clarification limit reached for this assignment." },
      response: new Response(null, { status: 422 }),
    } as never);

    render(<ClarificationsPanel attestationId="att-1" canWrite />);

    fireEvent.click(await screen.findByRole("button", { name: /Ask Question/i }));
    fireEvent.change(
      screen.getByPlaceholderText(/Describe what you need clarified/i),
      { target: { value: "Which version is in scope?" } },
    );
    fireEvent.click(screen.getByRole("button", { name: /Send Question/i }));

    expect(
      await screen.findByText(/Clarification limit reached/i),
    ).toBeInTheDocument();
    expect(alertSpy).not.toHaveBeenCalled();
  });
});
