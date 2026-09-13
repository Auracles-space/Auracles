/**
 * Unit coverage for the shared admin reason field.
 *
 * The field is the single place the owner-visible reason copy and its
 * 5 to 500 character rule live, so the tests pin both.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  REASON_MAX_LENGTH,
  REASON_MIN_LENGTH,
  ReasonField,
  isReasonValid,
} from "@/components/modules/admin/reason-field";

describe("ReasonField", () => {
  it("labels the textarea, explains the rule, and reports edits", () => {
    const onChange = vi.fn();
    render(<ReasonField id="why" onChange={onChange} value="" />);

    const field = screen.getByLabelText("Reason (shown to the organization's owner)");
    expect(field).toBeRequired();
    expect(field).toHaveAttribute("maxlength", String(REASON_MAX_LENGTH));
    expect(
      screen.getByText("Explain the decision in plain language. 5 to 500 characters."),
    ).toBeInTheDocument();

    fireEvent.change(field, { target: { value: "Because" } });
    expect(onChange).toHaveBeenCalledWith("Because");
  });

  it("accepts a custom label", () => {
    render(<ReasonField id="why" label="Why revoke?" onChange={() => undefined} value="" />);
    expect(screen.getByLabelText("Why revoke?")).toBeInTheDocument();
  });

  it("validates on the trimmed length", () => {
    expect(REASON_MIN_LENGTH).toBe(5);
    expect(isReasonValid("    abcd    ")).toBe(false);
    expect(isReasonValid("abcde")).toBe(true);
    expect(isReasonValid("x".repeat(REASON_MAX_LENGTH))).toBe(true);
    expect(isReasonValid("x".repeat(REASON_MAX_LENGTH + 1))).toBe(false);
  });
});
