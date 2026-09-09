import { describe, expect, it } from "vitest";

import { currencySymbol } from "@/lib/marketplace/currency";

describe("currencySymbol", () => {
  it("returns the naira sign for NGN, not the ISO code", () => {
    // The escrow-split field labels read "(₦)"; CLDR's default symbol for NGN
    // outside en-NG is the code itself, which makes that label read "(NGN)".
    expect(currencySymbol("NGN")).toBe("₦");
  });

  it("still returns the familiar symbol for major currencies", () => {
    expect(currencySymbol("USD")).toBe("$");
    expect(currencySymbol("GBP")).toBe("£");
  });
});
