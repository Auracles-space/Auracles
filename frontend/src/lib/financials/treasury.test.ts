/**
 * Tests for Treasury page helpers.
 */
import { describe, expect, it } from "vitest";

import {
  bankAccountOnHold,
  isNegativeAmount,
  recentStatementMonths,
} from "@/lib/financials/treasury";

describe("recentStatementMonths", () => {
  it("lists months newest first in Lagos time", () => {
    // 23:30 UTC on 31 August is already September in Lagos (UTC+1).
    const months = recentStatementMonths(new Date("2026-08-31T23:30:00Z"), 3);

    expect(months).toEqual(["2026-09", "2026-08", "2026-07"]);
  });

  it("crosses a year boundary", () => {
    expect(recentStatementMonths(new Date("2026-01-15T12:00:00Z"), 2)).toEqual([
      "2026-01",
      "2025-12",
    ]);
  });
});

describe("isNegativeAmount", () => {
  it("reads API decimal strings", () => {
    expect(isNegativeAmount("-0.01")).toBe(true);
    expect(isNegativeAmount("0.00")).toBe(false);
    expect(isNegativeAmount(null)).toBe(false);
  });
});

describe("bankAccountOnHold", () => {
  it("is on hold until usable_from", () => {
    const now = new Date("2026-09-16T12:00:00Z");
    expect(bankAccountOnHold({ usable_from: "2026-09-17T00:00:00Z" }, now)).toBe(true);
    expect(bankAccountOnHold({ usable_from: "2026-09-16T11:59:00Z" }, now)).toBe(false);
    expect(bankAccountOnHold(null, now)).toBe(false);
  });
});
