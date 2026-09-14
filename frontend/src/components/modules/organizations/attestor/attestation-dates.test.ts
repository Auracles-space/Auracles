import { describe, expect, it } from "vitest";

import {
  describeOfferExpiry,
  formatAttestationDate,
  isOverdue,
} from "./attestation-dates";

const NOW = new Date("2026-09-14T12:00:00Z");

describe("describeOfferExpiry", () => {
  it("counts down in hours inside the last two days", () => {
    expect(describeOfferExpiry("2026-09-15T17:00:00Z", NOW)).toEqual({
      label: "Expires in 29 h",
      expired: false,
    });
  });

  it("counts down in days and hours beyond two days", () => {
    expect(describeOfferExpiry("2026-09-17T15:00:00Z", NOW)).toEqual({
      label: "Expires in 3 d 3 h",
      expired: false,
    });
  });

  it("switches to days and hours exactly at the two-day mark", () => {
    expect(describeOfferExpiry("2026-09-16T12:00:00Z", NOW).label).toBe(
      "Expires in 2 d 0 h",
    );
  });

  it("says under an hour rather than zero hours", () => {
    expect(describeOfferExpiry("2026-09-14T12:30:00Z", NOW).label).toBe(
      "Expires in under 1 h",
    );
  });

  it("reports a past expiry as expired", () => {
    expect(describeOfferExpiry("2026-09-14T11:59:00Z", NOW)).toEqual({
      label: "Expired",
      expired: true,
    });
  });

  it("does not throw on an unparseable timestamp", () => {
    expect(describeOfferExpiry("not-a-date", NOW)).toEqual({
      label: "No expiry date",
      expired: false,
    });
  });
});

describe("formatAttestationDate", () => {
  it("formats an ISO timestamp as a short day-month-year date", () => {
    // en-GB abbreviates September as "Sept"; October is "17 Oct 2026".
    expect(formatAttestationDate("2026-09-17T15:00:00Z")).toBe("17 Sep 2026");
    expect(formatAttestationDate("2026-10-17T15:00:00Z")).toBe("17 Oct 2026");
  });

  it("returns an em dash when there is no date", () => {
    expect(formatAttestationDate(null)).toBe("—");
  });
});

describe("isOverdue", () => {
  it("is true once the due date has passed", () => {
    expect(isOverdue("2026-09-13T00:00:00Z", NOW)).toBe(true);
  });

  it("is false for a future or missing due date", () => {
    expect(isOverdue("2026-09-20T00:00:00Z", NOW)).toBe(false);
    expect(isOverdue(null, NOW)).toBe(false);
  });
});
