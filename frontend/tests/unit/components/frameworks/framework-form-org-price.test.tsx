import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { FrameworkForm } from "@/components/modules/frameworks/framework-form";

describe("FrameworkForm org pricing tier", () => {
  it("reveals the org price field only when the organizational tier is selected", () => {
    render(<FrameworkForm onSubmit={async () => undefined} />);

    expect(
      screen.queryByLabelText(/organization price/i),
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getByLabelText(/^organizational$/i));

    expect(screen.getByLabelText(/organization price/i)).toBeInTheDocument();
  });
});
