import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";

import { BankAccountCard } from "./bank-account-card";

const setBankAccount = vi.fn(async () => ({
  data: {},
  error: undefined,
  response: { ok: true },
}));
const resolveAccount = vi.fn(async () => ({
  data: { account_name: "AURACLES TECHNOLOGIES LTD" },
  error: undefined,
  response: { ok: true },
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  adminSetPlatformBankAccountV1AdminTreasuryBankAccountPut: (...args: unknown[]) =>
    setBankAccount(...(args as [])),
  adminTreasuryResolveAccountV1AdminTreasuryResolveAccountPost: (
    ...args: unknown[]
  ) => resolveAccount(...(args as [])),
  adminTreasuryBanksV1AdminTreasuryBanksGet: vi.fn(async () => ({
    data: { banks: [{ code: "058", name: "Guaranty Trust Bank" }] },
    error: undefined,
    response: { ok: true },
  })),
}));

vi.mock("@/lib/auth/form-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/auth/form-client")>()),
  configureBrowserClient: vi.fn(),
  getAccessTokenHeaders: () => ({ Authorization: "Bearer test" }),
}));

/** Open the editor and fill in a complete set of bank details. */
async function enterDetails() {
  fireEvent.click(screen.getByRole("button", { name: /set bank account/i }));
  fireEvent.change(await screen.findByLabelText(/bank/i), {
    target: { value: "058" },
  });
  fireEvent.change(screen.getByLabelText(/account number/i), {
    target: { value: "0123456789" },
  });
}

describe("BankAccountCard", () => {
  beforeEach(() => vi.clearAllMocks());

  it("names the account holder before the platform account is set", async () => {
    // This is where the platform's own money goes. A mistyped number belongs
    // to a real stranger, and the name is the only signal before it is saved.
    render(<BankAccountCard account={null} canEdit onChanged={vi.fn()} />);
    await enterDetails();
    fireEvent.click(screen.getByRole("button", { name: /check account/i }));

    expect(
      await screen.findByText("AURACLES TECHNOLOGIES LTD"),
    ).toBeInTheDocument();
    expect(setBankAccount).not.toHaveBeenCalled();
  });

  it("sets the account only once the name is accepted", async () => {
    const onChanged = vi.fn();
    render(<BankAccountCard account={null} canEdit onChanged={onChanged} />);
    await enterDetails();
    fireEvent.click(screen.getByRole("button", { name: /check account/i }));
    fireEvent.click(
      await screen.findByRole("button", { name: /yes, use this account/i }),
    );

    await waitFor(() => expect(setBankAccount).toHaveBeenCalledTimes(1));
    expect(setBankAccount).toHaveBeenCalledWith(
      expect.objectContaining({
        body: { account_number: "0123456789", bank_code: "058" },
      }),
    );
    expect(onChanged).toHaveBeenCalled();
  });

  it("does not offer the editor to an admin who cannot change it", () => {
    render(
      <BankAccountCard account={null} canEdit={false} onChanged={vi.fn()} />,
    );

    expect(
      screen.queryByRole("button", { name: /set bank account/i }),
    ).not.toBeInTheDocument();
  });
});
