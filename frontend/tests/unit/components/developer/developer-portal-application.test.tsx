/**
 * Developer application panel gate tests.
 *
 * Verifies the apply submit button stays disabled until the required company
 * and use-case fields are filled, and that an optional website must be a valid
 * URL when present.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ApplicationPanel } from "@/components/modules/developer/developer-portal-application";

describe("ApplicationPanel", () => {
  it("disables the apply submit until required fields are valid", () => {
    render(
      <ApplicationPanel
        applications={[]}
        latestApplication={null}
        onSubmit={vi.fn()}
      />,
    );

    const submit = screen.getByRole("button", { name: "Submit application" });
    expect(submit).toBeDisabled();

    fireEvent.change(screen.getByLabelText("Company"), {
      target: { value: "Partner Systems Inc." },
    });
    expect(submit).toBeDisabled();

    fireEvent.change(screen.getByLabelText("Use case"), {
      target: { value: "Embed Framework discovery in a CRM." },
    });
    expect(submit).toBeEnabled();
  });

  it("rejects a malformed website but allows an empty optional website", () => {
    render(
      <ApplicationPanel
        applications={[]}
        latestApplication={null}
        onSubmit={vi.fn()}
      />,
    );

    const submit = screen.getByRole("button", { name: "Submit application" });
    fireEvent.change(screen.getByLabelText("Company"), {
      target: { value: "Partner Systems Inc." },
    });
    fireEvent.change(screen.getByLabelText("Use case"), {
      target: { value: "Embed Framework discovery in a CRM." },
    });
    expect(submit).toBeEnabled();

    fireEvent.change(screen.getByLabelText("Website"), {
      target: { value: "not-a-url" },
    });
    expect(submit).toBeDisabled();

    fireEvent.change(screen.getByLabelText("Website"), {
      target: { value: "https://partners.example.com" },
    });
    expect(submit).toBeEnabled();
  });
});
