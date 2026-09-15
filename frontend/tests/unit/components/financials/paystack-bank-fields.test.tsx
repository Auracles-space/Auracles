/**
 * Paystack bank selector.
 *
 * Paystack's bank list can name two institutions under one code (e.g. two
 * microfinance banks sharing 50572); every entry must still render once, with
 * no duplicate React keys.
 */
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PaystackBankFields } from "@/components/modules/financials/paystack-bank-fields";
import { listPayoutBanks } from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  describeGeneratedError: vi.fn(() => "error"),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer t" })),
}));
vi.mock("@/lib/generated/sdk.gen", () => ({ listPayoutBanks: vi.fn() }));

describe("PaystackBankFields", () => {
  afterEach(() => vi.restoreAllMocks());

  it("lists each bank once, keeping distinct banks that share a code", async () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    vi.mocked(listPayoutBanks).mockResolvedValue({
      data: {
        banks: [
          { code: "057", name: "Zenith Bank" },
          { code: "057", name: "Zenith Bank" },
          { code: "50572", name: "Alpha Microfinance Bank" },
          { code: "50572", name: "Beta Microfinance Bank" },
          { code: "058", name: "Guaranty Trust Bank" },
        ],
      },
      response: { ok: true },
    } as never);

    render(
      <PaystackBankFields
        accountNumber=""
        bankCode=""
        onAccountNumberChange={vi.fn()}
        onBankCodeChange={vi.fn()}
      />,
    );

    expect(await screen.findByRole("option", { name: "Beta Microfinance Bank" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Alpha Microfinance Bank" })).toBeInTheDocument();
    expect(screen.getAllByRole("option", { name: "Zenith Bank" })).toHaveLength(1);
    const duplicateKeyWarnings = consoleError.mock.calls.filter((call) =>
      String(call[0]).includes("same key"),
    );
    expect(duplicateKeyWarnings).toEqual([]);
  });
});
