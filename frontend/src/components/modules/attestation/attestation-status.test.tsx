import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { StatusTag } from "./attestation-status";

describe("StatusTag requestor-friendly labels", () => {
  it("shows 'Finding attestor' instead of the raw needs_admin status", () => {
    render(<StatusTag value="needs_admin" />);
    expect(screen.getByText("Finding attestor")).toBeInTheDocument();
    expect(screen.queryByText(/needs admin/i)).toBeNull();
  });

  it("labels pending_fee as awaiting payment", () => {
    render(<StatusTag value="pending_fee" />);
    expect(screen.getByText("Awaiting payment")).toBeInTheDocument();
  });

  it("falls back to title-casing for unmapped statuses", () => {
    render(<StatusTag value="accepted" />);
    expect(screen.getByText("Accepted")).toBeInTheDocument();
  });
});
