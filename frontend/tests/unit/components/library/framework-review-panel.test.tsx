import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { FrameworkReviewPanel } from "@/components/modules/library/framework-review-panel";
import {
  createFrameworkReview,
  getCurrentUser,
  listFrameworkReviews,
  updateMyFrameworkReview,
} from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: (error: { detail?: string } | undefined) =>
    error?.detail ?? "The request could not be completed.",
  getAccessTokenHeaders: () => ({ Authorization: "Bearer access-token" }),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  client: { setConfig: vi.fn() },
  createFrameworkReview: vi.fn(),
  getCurrentUser: vi.fn(),
  listFrameworkReviews: vi.fn(),
  updateMyFrameworkReview: vi.fn(),
}));

function ok<T>(data: T) {
  return { data, error: undefined, response: new Response(null, { status: 200 }) };
}

describe("FrameworkReviewPanel", () => {
  beforeEach(() => {
    vi.mocked(getCurrentUser).mockReset();
    vi.mocked(listFrameworkReviews).mockReset();
    vi.mocked(createFrameworkReview).mockReset();
    vi.mocked(updateMyFrameworkReview).mockReset();
  });

  it("submits a new review when the operator has none yet", async () => {
    vi.mocked(getCurrentUser).mockResolvedValue(ok({ id: "u1" }));
    vi.mocked(listFrameworkReviews).mockResolvedValue(
      ok({ reviews: [], average_score: null, review_count: 0 }),
    );
    vi.mocked(createFrameworkReview).mockResolvedValue(
      ok({ operator_id: "u1", score: 4, body: "Helped a lot." }),
    );

    render(<FrameworkReviewPanel frameworkId="fw-1" />);

    const submit = await screen.findByRole("button", { name: /submit review/i });
    fireEvent.click(screen.getByRole("radio", { name: "4" }));
    fireEvent.change(screen.getByPlaceholderText(/what changed/i), {
      target: { value: "Helped a lot." },
    });
    fireEvent.click(submit);

    expect(await screen.findByText(/review submitted/i)).toBeInTheDocument();
    expect(vi.mocked(createFrameworkReview)).toHaveBeenCalledWith({
      body: { body: "Helped a lot.", score: 4 },
      headers: { Authorization: "Bearer access-token" },
      path: { framework_id: "fw-1" },
    });
  });

  it("prefills and updates an existing review", async () => {
    vi.mocked(getCurrentUser).mockResolvedValue(ok({ id: "u1" }));
    vi.mocked(listFrameworkReviews).mockResolvedValue(
      ok({
        reviews: [{ operator_id: "u1", score: 3, body: "Initial." }],
        average_score: "3.0",
        review_count: 1,
      }),
    );
    vi.mocked(updateMyFrameworkReview).mockResolvedValue(
      ok({ operator_id: "u1", score: 3, body: "Updated." }),
    );

    render(<FrameworkReviewPanel frameworkId="fw-1" />);

    const update = await screen.findByRole("button", { name: /update review/i });
    fireEvent.click(update);

    expect(await screen.findByText(/review updated/i)).toBeInTheDocument();
    expect(vi.mocked(updateMyFrameworkReview)).toHaveBeenCalled();
  });

  it("shows an error when the review context fails to load", async () => {
    vi.mocked(getCurrentUser).mockResolvedValue(ok({ id: "u1" }));
    vi.mocked(listFrameworkReviews).mockResolvedValue({
      data: undefined,
      error: { detail: "Reviews are unavailable." },
      response: new Response(null, { status: 502 }),
    });

    render(<FrameworkReviewPanel frameworkId="fw-1" />);

    expect(
      await screen.findByText(/reviews are unavailable/i),
    ).toBeInTheDocument();
  });
});
