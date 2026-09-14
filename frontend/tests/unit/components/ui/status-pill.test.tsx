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

describe("organization people vocabulary", () => {
  it("names invitation outcomes so history reads without raw enums", () => {
    expect(describeStatus("declined")).toEqual({ label: "Declined", tone: "error" });
    expect(describeStatus("expired")).toEqual({ label: "Expired", tone: "neutral" });
    expect(describeStatus("revoked")).toEqual({ label: "Revoked", tone: "error" });
  });

  it("renders membership roles as neutral pills with title-case labels", () => {
    expect(describeStatus("owner")).toEqual({ label: "Owner", tone: "neutral" });
    expect(describeStatus("admin")).toEqual({ label: "Admin", tone: "neutral" });
    expect(describeStatus("member")).toEqual({ label: "Member", tone: "neutral" });
  });
});

describe("framework and license vocabulary", () => {
  it("keeps pipeline jargon out of the contributor-facing labels", () => {
    expect(describeStatus("pipeline_failed")).toEqual({
      label: "Processing failed",
      tone: "error",
    });
    expect(describeStatus("pipeline_passed")).toEqual({
      label: "Ready to publish",
      tone: "success",
    });
    expect(describeStatus("processing")).toEqual({ label: "Processing", tone: "info" });
    expect(describeStatus("published")).toEqual({ label: "Published", tone: "success" });
    expect(describeStatus("unpublished")).toEqual({ label: "Unpublished", tone: "neutral" });
  });

  it("reads a lapsed or pulled license as such", () => {
    expect(describeStatus("expired").label).toBe("Expired");
    expect(describeStatus("revoked").tone).toBe("error");
    expect(describeStatus("active")).toEqual({ label: "Active", tone: "success" });
  });
});

describe("payout vocabulary", () => {
  it("reads payout lifecycle states in plain words with semantic tones", () => {
    expect(describeStatus("pending")).toEqual({ label: "Pending", tone: "warning" });
    expect(describeStatus("processing")).toEqual({ label: "Processing", tone: "info" });
    expect(describeStatus("completed")).toEqual({ label: "Paid", tone: "success" });
    expect(describeStatus("paid")).toEqual({ label: "Paid", tone: "success" });
    expect(describeStatus("failed")).toEqual({ label: "Failed", tone: "error" });
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
