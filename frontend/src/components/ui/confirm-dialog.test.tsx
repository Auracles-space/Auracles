/**
 * Tests for the shared confirmation dialog.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import { ConfirmDialog } from "@/components/ui/confirm-dialog";

/** A dialog asking for input, with an inline close handler like real callers. */
function AmountDialog() {
  const [amount, setAmount] = useState("");
  return (
    <ConfirmDialog
      confirmDisabled={amount === ""}
      confirmLabel="Withdraw"
      description={
        <label>
          Amount
          <input onChange={(event) => setAmount(event.target.value)} value={amount} />
        </label>
      }
      onClose={() => setAmount("")}
      onConfirm={() => undefined}
      open
      title="Withdraw platform money"
    />
  );
}

describe("ConfirmDialog", () => {
  it("keeps focus in the field while the admin types", () => {
    // Every keystroke re-renders the caller with a new onClose; the dialog used
    // to treat that as opening again and pull focus to the confirm button.
    render(<AmountDialog />);
    const input = screen.getByLabelText("Amount");
    expect(input).toHaveFocus();

    fireEvent.change(input, { target: { value: "1" } });
    expect(input).toHaveFocus();

    fireEvent.change(input, { target: { value: "10" } });
    expect(input).toHaveFocus();
  });
});
