import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { OnboardingPrompt } from "@/components/modules/auth/onboarding-prompt";

describe("OnboardingPrompt", () => {
  it("keeps browse and preview available while prompting profile and KYC completion", () => {
    render(<OnboardingPrompt />);

    expect(screen.getByText(/complete your profile/i)).toBeInTheDocument();
    expect(screen.getByText(/verify your identity/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /browse frameworks/i })).toHaveAttribute(
      "href",
      "/explore",
    );
  });
});
