import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";

import { ConfirmBankAccount } from "./confirm-bank-account";

vi.mock("@/lib/generated/sdk.gen", () => ({
  listPayoutBanks: vi.fn(async () => ({
    data: { banks: [{ code: "044", name: "Access Bank" }] },
    error: undefined,
    response: { ok: true },
  })),
}));

vi.mock("@/lib/auth/form-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/auth/form-client")>()),
  configureBrowserClient: vi.fn(),
  getAccessTokenHeaders: () => ({ Authorization: "Bearer test" }),
}));

/** Fill in a complete set of bank details. */
async function enterDetails() {
  fireEvent.change(await screen.findByLabelText(/bank/i), {
    target: { value: "044" },
  });
  fireEvent.change(screen.getByLabelText(/account number/i), {
    target: { value: "0123456789" },
  });
}

describe("ConfirmBankAccount", () => {
  beforeEach(() => vi.clearAllMocks());

  it("names the account holder before anything is registered", async () => {
    // A mistyped number usually belongs to a real stranger, so the name is the
    // only signal that the digits are wrong.
    const resolve = vi.fn(async () => ({ name: "ADA LOVELACE" }));
    const onConfirm = vi.fn(async () => null);

    render(
      <ConfirmBankAccount
        idPrefix="test"
        onConfirm={onConfirm}
        resolve={resolve}
      />,
    );
    await enterDetails();
    fireEvent.click(screen.getByRole("button", { name: /check account/i }));

    expect(await screen.findByText("ADA LOVELACE")).toBeInTheDocument();
    expect(resolve).toHaveBeenCalledWith({
      accountNumber: "0123456789",
      bankCode: "044",
    });
    // Nothing is registered until the name has been accepted.
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("registers the account only once the name is accepted", async () => {
    const resolve = vi.fn(async () => ({ name: "ADA LOVELACE" }));
    const onConfirm = vi.fn(async () => null);

    render(
      <ConfirmBankAccount
        idPrefix="test"
        onConfirm={onConfirm}
        resolve={resolve}
      />,
    );
    await enterDetails();
    fireEvent.click(screen.getByRole("button", { name: /check account/i }));
    fireEvent.click(await screen.findByRole("button", { name: /yes, use/i }));

    await waitFor(() =>
      expect(onConfirm).toHaveBeenCalledWith({
        accountNumber: "0123456789",
        bankCode: "044",
      }),
    );
  });

  it("lets the person reject the name and correct the number", async () => {
    // This is the whole point: the recovery path has to be in front of them at
    // the moment they see a name that is not theirs.
    const resolve = vi.fn(async () => ({ name: "SOMEBODY ELSE" }));
    const onConfirm = vi.fn(async () => null);

    render(
      <ConfirmBankAccount
        idPrefix="test"
        onConfirm={onConfirm}
        resolve={resolve}
      />,
    );
    await enterDetails();
    fireEvent.click(screen.getByRole("button", { name: /check account/i }));
    fireEvent.click(await screen.findByRole("button", { name: /no, change/i }));

    expect(screen.queryByText("SOMEBODY ELSE")).not.toBeInTheDocument();
    expect(onConfirm).not.toHaveBeenCalled();
    expect(
      screen.getByRole("button", { name: /check account/i }),
    ).toBeInTheDocument();
  });

  it("surfaces a lookup failure instead of registering blindly", async () => {
    const resolve = vi.fn(async () => ({
      error: "That account number could not be found at the bank you selected.",
    }));
    const onConfirm = vi.fn(async () => null);

    render(
      <ConfirmBankAccount
        idPrefix="test"
        onConfirm={onConfirm}
        resolve={resolve}
      />,
    );
    await enterDetails();
    fireEvent.click(screen.getByRole("button", { name: /check account/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /could not be found/i,
    );
    expect(onConfirm).not.toHaveBeenCalled();
  });
});
