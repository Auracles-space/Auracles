/**
 * Waitlist-stage email collector.
 *
 * Temporary stand-in for the platform's POST /v1/waitlist while only the
 * frontend is deployed: the landing form posts here, and this handler
 * forwards the address to a Resend Audience (the list the launch broadcast
 * will be sent from). Mirrors the backend contract — idempotent joins, the
 * same { already_joined, message } response shape — so the form component
 * does not care which collector is live.
 *
 * Delete at full launch: flip NEXT_PUBLIC_WAITLIST_MODE off (which makes
 * this route inert), point the form back at the generated client, and import
 * the Resend Audience into `waitlist_entries`.
 */
import { NextResponse } from "next/server";

const RESEND_API_BASE = "https://api.resend.com";
const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const MAX_EMAIL_LENGTH = 254;

const JOINED_MESSAGE = "You've been added to the waitlist.";
const ALREADY_JOINED_MESSAGE =
  "You're already on the waitlist — we'll be in touch.";
const UNAVAILABLE_MESSAGE =
  "We couldn't add you right now. Please try again later.";

/** Shape of the (untrusted) form submission body. */
type WaitlistSubmission = {
  email?: unknown;
  /** Honeypot — humans never see or fill this field. */
  website?: unknown;
};

/** Build the JSON success payload shared with the real backend endpoint. */
function joinResponse(alreadyJoined: boolean, status: number): NextResponse {
  return NextResponse.json(
    {
      already_joined: alreadyJoined,
      message: alreadyJoined ? ALREADY_JOINED_MESSAGE : JOINED_MESSAGE,
    },
    { status },
  );
}

/**
 * Record a waitlist email in the Resend Audience.
 *
 * Validation happens before any provider call; honeypot submissions return
 * a fake success so bots learn nothing. Provider failures surface as an
 * opaque 502 — no Resend details reach the browser.
 */
export async function POST(request: Request): Promise<NextResponse> {
  if (process.env.NEXT_PUBLIC_WAITLIST_MODE === "false") {
    return NextResponse.json({ message: "Not found." }, { status: 404 });
  }

  let submission: WaitlistSubmission;
  try {
    submission = (await request.json()) as WaitlistSubmission;
  } catch {
    return NextResponse.json(
      { message: "A valid email address is required." },
      { status: 422 },
    );
  }

  const email =
    typeof submission.email === "string"
      ? submission.email.trim().toLowerCase()
      : "";
  if (
    !email ||
    email.length > MAX_EMAIL_LENGTH ||
    !EMAIL_PATTERN.test(email)
  ) {
    return NextResponse.json(
      { message: "A valid email address is required." },
      { status: 422 },
    );
  }

  // Bots that fill every field get a convincing success and no side effects.
  if (typeof submission.website === "string" && submission.website !== "") {
    return joinResponse(false, 201);
  }

  const apiKey = process.env.RESEND_API_KEY;
  const audienceId = process.env.RESEND_AUDIENCE_ID;
  if (!apiKey || !audienceId) {
    console.error("waitlist collector missing RESEND configuration");
    return NextResponse.json({ message: UNAVAILABLE_MESSAGE }, { status: 502 });
  }

  let providerResponse: Response;
  try {
    providerResponse = await fetch(
      `${RESEND_API_BASE}/audiences/${audienceId}/contacts`,
      {
        body: JSON.stringify({ email, unsubscribed: false }),
        headers: {
          Authorization: `Bearer ${apiKey}`,
          "Content-Type": "application/json",
        },
        method: "POST",
      },
    );
  } catch {
    console.error("waitlist collector could not reach the email provider");
    return NextResponse.json({ message: UNAVAILABLE_MESSAGE }, { status: 502 });
  }

  if (providerResponse.ok) {
    return joinResponse(false, 201);
  }
  if (providerResponse.status === 409) {
    return joinResponse(true, 200);
  }

  console.error(
    `waitlist collector provider error status=${providerResponse.status}`,
  );
  return NextResponse.json({ message: UNAVAILABLE_MESSAGE }, { status: 502 });
}
