import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  attestationStatusKey,
  describeStatus,
  offerStatusKey,
  StatusPill,
} from "@/components/ui/status-pill";

describe("describeStatus", () => {
  it("maps operational statuses to one label and tone everywhere", () => {
    expect(describeStatus("needs_info")).toEqual({ label: "Needs info", tone: "warning" });
    expect(describeStatus("in_review")).toEqual({ label: "In review", tone: "warning" });
    expect(describeStatus("needs_admin")).toEqual({ label: "Needs admin", tone: "error" });
    expect(describeStatus("matching")).toEqual({ label: "Finding attestor", tone: "info" });
    expect(describeStatus("approved")).toEqual({ label: "Approved", tone: "success" });
    expect(describeStatus("revoked")).toEqual({ label: "Revoked", tone: "error" });
  });

  it("title-cases unknown statuses with a neutral tone", () => {
    expect(describeStatus("some_new_state")).toEqual({
      label: "Some New State",
      tone: "neutral",
    });
  });
});

describe("StatusPill", () => {
  it("renders the mapped label and tone classes", () => {
    render(<StatusPill status="needs_admin" />);

    const pill = screen.getByText("Needs admin");
    expect(pill.className).toContain("text-error");
    expect(pill.className).toContain("rounded-badge");
  });

  it("accepts a label override without changing the tone", () => {
    render(<StatusPill label="Trial passed" status="passed" />);

    expect(screen.getByText("Trial passed").className).toContain("text-success");
  });
});

describe("owner-facing vocabulary", () => {
  it("names a resubmittable KYB rejection Needs changes", () => {
    expect(describeStatus("needs_changes")).toEqual({
      label: "Needs changes",
      tone: "warning",
    });
  });
});

describe("attestation vocabulary per viewer", () => {
  it("hides the admin step from the requestor: needs_admin reads Finding attestor", () => {
    expect(describeStatus(attestationStatusKey("needs_admin", "requestor"))).toEqual({
      label: "Finding attestor",
      tone: "info",
    });
    expect(describeStatus(attestationStatusKey("needs_admin", "admin"))).toEqual({
      label: "Needs admin",
      tone: "error",
    });
  });

  it("reads a submitted report as ready for the requestor and submitted for the org", () => {
    expect(describeStatus(attestationStatusKey("report_submitted", "requestor")).label).toBe(
      "Report ready",
    );
    expect(describeStatus(attestationStatusKey("report_submitted", "attestor")).label).toBe(
      "Submitted",
    );
    expect(describeStatus(attestationStatusKey("report_submitted", "admin")).label).toBe(
      "Submitted",
    );
  });

  it("leaves every other status untouched", () => {
    expect(attestationStatusKey("in_review", "requestor")).toBe("in_review");
    expect(attestationStatusKey("released", "attestor")).toBe("released");
  });

  it("names an open offer as awaiting the org's response", () => {
    expect(describeStatus(offerStatusKey("offered"))).toEqual({
      label: "Awaiting your response",
      tone: "warning",
    });
    expect(offerStatusKey("declined")).toBe("declined");
  });
});
