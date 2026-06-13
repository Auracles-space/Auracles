"use client";

/**
 * Licensed Framework review panel.
 *
 * Lets an Operator create or edit their one review for a Framework they already
 * hold in their Library. The backend remains authoritative for license checks,
 * duplicate review prevention, and the 30-day edit window.
 */
import { FormEvent, useEffect, useState } from "react";

import {
  createFrameworkReview,
  getCurrentUser,
  listFrameworkReviews,
  updateMyFrameworkReview,
} from "@/lib/generated/sdk.gen";
import type {
  FrameworkReviewListResponse,
  FrameworkReviewResponse,
} from "@/lib/generated/types.gen";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";

type FrameworkReviewPanelProps = {
  frameworkId: string;
};

type ReviewPanelState = {
  error: string | null;
  loading: boolean;
  myReview: FrameworkReviewResponse | null;
  reviews: FrameworkReviewListResponse | null;
  userId: string | null;
};

/**
 * Render the current Operator's review form and aggregate review context.
 *
 * @param props - Licensed Framework id from the Operator Library item.
 */
export function FrameworkReviewPanel({ frameworkId }: FrameworkReviewPanelProps) {
  const [body, setBody] = useState("");
  const [score, setScore] = useState(5);
  const [saving, setSaving] = useState(false);
  const [savedMessage, setSavedMessage] = useState<string | null>(null);
  const [state, setState] = useState<ReviewPanelState>({
    error: null,
    loading: true,
    myReview: null,
    reviews: null,
    userId: null,
  });

  useEffect(() => {
    async function loadReviews() {
      configureBrowserClient();
      const headers = getAccessTokenHeaders();
      const [userResult, reviewResult] = await Promise.all([
        getCurrentUser({ headers }),
        listFrameworkReviews({
          headers,
          path: { framework_id: frameworkId },
        }),
      ]);

      if (!userResult.response.ok || !userResult.data) {
        setState((current) => ({
          ...current,
          error: describeGeneratedError(userResult.error),
          loading: false,
        }));
        return;
      }

      if (!reviewResult.response.ok || !reviewResult.data) {
        setState((current) => ({
          ...current,
          error: describeGeneratedError(reviewResult.error),
          loading: false,
          userId: userResult.data.id,
        }));
        return;
      }

      const review =
        reviewResult.data.reviews.find(
          (candidate: FrameworkReviewResponse) =>
            candidate.operator_id === userResult.data.id,
        ) ?? null;
      setScore(review?.score ?? 5);
      setBody(review?.body ?? "");
      setState({
        error: null,
        loading: false,
        myReview: review,
        reviews: reviewResult.data,
        userId: userResult.data.id,
      });
    }

    void loadReviews();
  }, [frameworkId]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setSavedMessage(null);
    setState((current) => ({ ...current, error: null }));
    configureBrowserClient();

    const payload = {
      body: body.trim() ? body.trim() : null,
      score,
    };
    const result = state.myReview
      ? await updateMyFrameworkReview({
          body: payload,
          headers: getAccessTokenHeaders(),
          path: { framework_id: frameworkId },
        })
      : await createFrameworkReview({
          body: payload,
          headers: getAccessTokenHeaders(),
          path: { framework_id: frameworkId },
        });

    if (!result.response.ok || !result.data) {
      setState((current) => ({
        ...current,
        error: describeGeneratedError(result.error),
      }));
      setSaving(false);
      return;
    }

    const reviewResult = await listFrameworkReviews({
      headers: getAccessTokenHeaders(),
      path: { framework_id: frameworkId },
    });
    setState((current) => ({
      ...current,
      error: null,
      myReview: result.data,
      reviews: reviewResult.data ?? current.reviews,
    }));
    setSavedMessage(state.myReview ? "Review updated." : "Review submitted.");
    setSaving(false);
  }

  if (state.loading) {
    return <p className="mt-4 text-sm text-foreground-muted">Loading reviews.</p>;
  }

  const aggregate = state.reviews?.average_score
    ? `${state.reviews.average_score} average from ${state.reviews.review_count} review${
        state.reviews.review_count === 1 ? "" : "s"
      }`
    : "No reviews yet";

  return (
    <section className="mt-5 border-t border-border-default pt-5">
      <div className="flex flex-col gap-1">
        <p className="text-sm font-semibold text-foreground">Your review</p>
        <p className="text-sm text-foreground-muted">{aggregate}</p>
      </div>
      <form className="mt-4 grid gap-3" onSubmit={handleSubmit}>
        <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="Review score">
          {[1, 2, 3, 4, 5].map((value) => (
            <button
              aria-checked={score === value}
              className={[
                "min-h-12 rounded-xl border px-3 text-sm font-semibold",
                score === value
                  ? "border-accent bg-accent text-background"
                  : "border-border-default bg-background text-foreground hover:bg-surface-3",
              ].join(" ")}
              key={value}
              onClick={() => setScore(value)}
              role="radio"
              type="button"
            >
              {value}
            </button>
          ))}
        </div>
        <label className="grid gap-2 text-sm font-medium text-foreground">
          Review body
          <textarea
            className="min-h-28 rounded-xl border border-border-default bg-background px-3 py-2 text-sm font-normal text-foreground outline-none focus-visible:ring-2 focus-visible:ring-accent"
            maxLength={4000}
            onChange={(event) => setBody(event.target.value)}
            placeholder="What changed after using this Framework?"
            value={body}
          />
        </label>
        {state.error ? <p className="text-sm text-error">{state.error}</p> : null}
        {savedMessage ? (
          <p className="text-sm text-success">{savedMessage}</p>
        ) : null}
        <button
          className="min-h-12 rounded-xl bg-foreground px-4 text-sm font-semibold text-background transition hover:bg-foreground/90 disabled:cursor-not-allowed disabled:opacity-60"
          disabled={saving}
          type="submit"
        >
          {saving
            ? "Saving"
            : state.myReview
              ? "Update review"
              : "Submit review"}
        </button>
      </form>
    </section>
  );
}
