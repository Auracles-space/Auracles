import { describe, expect, it, vi } from "vitest";

import {
  formatFrameworkStatus,
  formatListingPrice,
  formatMoney,
} from "@/lib/marketplace/format";

// A distinctive third currency: tests/setup.ts pins NEXT_PUBLIC_PLATFORM_CURRENCY
// to USD, so asserting against the real constant would pass even if the default
// were still hardcoded to dollars.
vi.mock("@/lib/marketplace/currency", () => ({
  CURRENCY_DISPLAY: "narrowSymbol",
  PLATFORM_CURRENCY: "GBP",
}));

describe("formatMoney", () => {
  it("falls back to the platform settlement currency, not dollars", () => {
    // Analytics and developer-portal figures arrive as bare decimal strings
    // with no currency field, so the default is what the admin actually reads.
    expect(formatMoney("350.00")).toContain("£");
    expect(formatMoney("350.00")).not.toContain("$");
  });

  it("still honours an explicit currency from the API record", () => {
    expect(formatMoney("350.00", "USD")).toContain("$");
  });

  it("prints the naira sign rather than the ISO code", () => {
    // CLDR's default symbol for NGN outside en-NG is the literal string "NGN",
    // so the pilot's own currency renders as a code on every chart and ledger
    // unless the narrow symbol is asked for by name.
    expect(formatMoney("350.00", "NGN")).toContain("₦");
    expect(formatMoney("350.00", "NGN")).not.toContain("NGN");
  });
});

describe("formatFrameworkStatus", () => {
  it("maps workflow statuses to plain contributor-facing labels", () => {
    expect(formatFrameworkStatus("draft")).toBe("Draft");
    expect(formatFrameworkStatus("processing")).toBe("Checking…");
    expect(formatFrameworkStatus("submitted")).toBe("Submitted");
    expect(formatFrameworkStatus("pipeline_passed")).toBe("Ready to publish");
    expect(formatFrameworkStatus("pipeline_failed")).toBe("Checks failed");
    expect(formatFrameworkStatus("published")).toBe("Published");
    expect(formatFrameworkStatus("unpublished")).toBe("Unpublished");
  });

  it("falls back to title-case for unknown values", () => {
    expect(formatFrameworkStatus("some_new_state")).toBe("Some New State");
    expect(formatFrameworkStatus(null)).toBe("Not set");
  });
});

describe("formatListingPrice", () => {
  it("renders a zero listing price as Free", () => {
    expect(formatListingPrice("0.00")).toBe("Free");
    expect(formatListingPrice("0")).toBe("Free");
  });

  it("formats a priced listing exactly as formatMoney does", () => {
    // Listings must not drift from every other money figure on the page just
    // because this helper knows about zero.
    expect(formatListingPrice("25000.00")).toBe(formatMoney("25000.00"));
    expect(formatListingPrice("499.50", "USD")).toBe(formatMoney("499.50", "USD"));
  });

  it("leaves a zero that is not a listing price alone", () => {
    // formatMoney is shared with payouts, earnings and invoices. A balance of
    // zero is a number, not an offer, and must keep reading as money.
    expect(formatMoney("0.00")).not.toBe("Free");
  });

  it("falls back to plain text for an unparseable amount", () => {
    expect(formatListingPrice("not-a-number")).toBe(formatMoney("not-a-number"));
  });
});
