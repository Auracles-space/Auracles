import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { TotpInput } from "@/components/modules/auth/totp-input";

describe("TotpInput", () => {
  it("accepts only six numeric TOTP characters", () => {
    const onChange = vi.fn();

    render(<TotpInput label="Authenticator code" onChange={onChange} value="" />);

    fireEvent.change(screen.getByLabelText(/authenticator code/i), {
      target: { value: "12a34-5678" },
    });

    expect(onChange).toHaveBeenCalledWith("123456");
  });
});
