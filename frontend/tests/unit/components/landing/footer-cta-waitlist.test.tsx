/**
 * Waitlist form behavior for the footer CTA.
 *
 * During the waitlist-only deployment there is no platform backend, so the
 * form must post to the app's own /api/waitlist route (which forwards to a
 * Resend Audience) rather than the generated FastAPI client. These tests pin
 * that submission target, the success and duplicate states, and the error
 * path.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { FooterCta } from "@/components/modules/landing/footer-cta";

describe("FooterCta waitlist form", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
    fetchMock.mockReset();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  /** Fill the email field and submit the waitlist form. */
  function submitEmail(email: string): void {
    fireEvent.change(screen.getByLabelText(/email address/i), {
      target: { value: email },
    });
    fireEvent.click(screen.getByRole("button", { name: /join waitlist/i }));
  }

  it("posts the email to the app's own /api/waitlist route", async () => {
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({ already_joined: false, message: "added" }),
        { status: 201 },
      ),
    );

    render(<FooterCta />);
    submitEmail("ada@example.com");

    await waitFor(() => {
      expect(
        screen.getByText(/you've been added to the waitlist/i),
      ).toBeInTheDocument();
    });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/waitlist");
    expect(JSON.parse(init.body).email).toBe("ada@example.com");
  });

  it("shows the repeat-join state for an already-registered email", async () => {
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({ already_joined: true, message: "already there" }),
        { status: 200 },
      ),
    );

    render(<FooterCta />);
    submitEmail("ada@example.com");

    await waitFor(() => {
      expect(
        screen.getByText(/you're already on the waitlist/i),
      ).toBeInTheDocument();
    });
  });

  it("surfaces an error message when the route rejects the submission", async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ message: "Please try again later." }), {
        status: 502,
      }),
    );

    render(<FooterCta />);
    submitEmail("ada@example.com");

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(
        /please try again later/i,
      );
    });
  });
});
