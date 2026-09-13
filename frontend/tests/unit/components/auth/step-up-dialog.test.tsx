import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { StepUpDialog } from "@/components/step-up-dialog";
import { requestStepUp, resetStepUpGate, stepUpStore } from "@/lib/auth/step-up-gate";

const sdkMock = vi.hoisted(() => ({
  openStepUp: vi.fn(),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  openStepUpV1AuthStepUpPost: sdkMock.openStepUp,
  client: { interceptors: { response: { use: vi.fn() } }, setConfig: vi.fn() },
}));

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  getAccessTokenHeaders: () => ({ Authorization: "Bearer test" }),
  describeGeneratedError: (error: unknown) =>
    (error as { detail?: string })?.detail ?? "The request could not be completed.",
}));

describe("StepUpDialog", () => {
  beforeEach(() => {
    resetStepUpGate();
    sdkMock.openStepUp.mockReset();
  });

  afterEach(() => {
    resetStepUpGate();
  });

  it("renders nothing until a prompt is requested", () => {
    render(<StepUpDialog />);

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("verifies the code, records the window, and settles the prompt", async () => {
    const verifiedUntil = new Date(Date.now() + 600_000).toISOString();
    sdkMock.openStepUp.mockResolvedValue({
      data: { verified_until: verifiedUntil },
      response: { ok: true, status: 200 },
    });
    render(<StepUpDialog />);

    let outcome: Promise<boolean> | null = null;
    act(() => {
      outcome = requestStepUp();
    });
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("Confirm it's you");

    fireEvent.change(screen.getByLabelText("Authenticator code"), {
      target: { value: "123456" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Verify" }));

    await expect(outcome!).resolves.toBe(true);
    expect(sdkMock.openStepUp).toHaveBeenCalledWith(
      expect.objectContaining({ body: { code: "123456" } }),
    );
    expect(stepUpStore.getState().verifiedUntil).toBe(Date.parse(verifiedUntil));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("shows the API error and keeps the prompt open on a wrong code", async () => {
    sdkMock.openStepUp.mockResolvedValue({
      error: { detail: "Invalid 2FA code." },
      response: { ok: false, status: 422 },
    });
    render(<StepUpDialog />);
    act(() => {
      void requestStepUp();
    });
    await screen.findByRole("dialog");

    fireEvent.change(screen.getByLabelText("Authenticator code"), {
      target: { value: "000000" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Verify" }));

    expect(await screen.findByText("Invalid 2FA code.")).toBeInTheDocument();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("settles false when the user cancels", async () => {
    render(<StepUpDialog />);
    let outcome: Promise<boolean> | null = null;
    act(() => {
      outcome = requestStepUp();
    });
    await screen.findByRole("dialog");

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    await expect(outcome!).resolves.toBe(false);
    expect(sdkMock.openStepUp).not.toHaveBeenCalled();
  });

  it("accepts a backup code with its hyphen", async () => {
    sdkMock.openStepUp.mockResolvedValue({
      data: { verified_until: new Date(Date.now() + 600_000).toISOString() },
      response: { ok: true, status: 200 },
    });
    render(<StepUpDialog />);
    act(() => {
      void requestStepUp();
    });
    await screen.findByRole("dialog");

    fireEvent.click(screen.getByRole("button", { name: "Use a backup code" }));
    fireEvent.change(screen.getByLabelText("Backup code"), {
      target: { value: "ab12-cd34" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Verify" }));

    await waitFor(() =>
      expect(sdkMock.openStepUp).toHaveBeenCalledWith(
        expect.objectContaining({ body: { code: "ab12-cd34" } }),
      ),
    );
  });
});
