import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { GoogleSignInButton } from "@/components/modules/auth/google-sign-in-button";

describe("GoogleSignInButton", () => {
  it("links to the Google start endpoint and forwards next + consent", () => {
    render(<GoogleSignInButton next="/explore/abc" termsAccepted />);

    const link = screen.getByRole("link", { name: /continue with google/i });
    const href = link.getAttribute("href") ?? "";
    expect(href).toContain("/v1/auth/google/start");
    expect(href).toContain("next=%2Fexplore%2Fabc");
    expect(href).toContain("terms=1");
  });

  it("does not carry consent when terms are not accepted", () => {
    render(<GoogleSignInButton termsAccepted={false} />);

    // No link is rendered; the control is an inert button until terms are accepted.
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /continue with google/i }),
    ).toBeDisabled();
  });

  it("drops an unsafe next path", () => {
    render(<GoogleSignInButton next="https://evil.example" termsAccepted />);

    const href = screen.getByRole("link").getAttribute("href") ?? "";
    expect(href).not.toContain("evil.example");
  });
});
