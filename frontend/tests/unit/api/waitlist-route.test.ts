/**
 * Route-handler tests for the waitlist-stage email collector.
 *
 * While the platform backend is not yet deployed, the landing page's waitlist
 * form posts to this Next.js route, which forwards the address to a Resend
 * Audience. These tests pin the contract: validation before any provider
 * call, honeypot submissions silently dropped, provider outcomes mapped to
 * the same { already_joined, message } shape the real backend returns, and
 * the route going inert once waitlist mode is switched off.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { POST } from "@/app/api/waitlist/route";

const RESEND_CONTACTS_URL =
  "https://api.resend.com/audiences/aud_123/contacts";

/** Build a POST request to the route with a JSON body. */
function jsonRequest(body: unknown): Request {
  return new Request("http://localhost/api/waitlist", {
    body: JSON.stringify(body),
    headers: { "content-type": "application/json" },
    method: "POST",
  });
}

describe("POST /api/waitlist", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    vi.stubEnv("RESEND_API_KEY", "re_test_key");
    vi.stubEnv("RESEND_AUDIENCE_ID", "aud_123");
    vi.stubEnv("NEXT_PUBLIC_WAITLIST_MODE", "true");
    vi.stubGlobal("fetch", fetchMock);
    fetchMock.mockReset();
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  it("adds a new email to the Resend audience and reports a first join", async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ id: "contact_1", object: "contact" }), {
        status: 201,
      }),
    );

    const response = await POST(jsonRequest({ email: "ada@example.com" }));
    const payload = await response.json();

    expect(response.status).toBe(201);
    expect(payload.already_joined).toBe(false);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(RESEND_CONTACTS_URL);
    expect(init.headers.Authorization).toBe("Bearer re_test_key");
    expect(JSON.parse(init.body).email).toBe("ada@example.com");
  });

  it("treats a provider conflict as an idempotent repeat join", async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ message: "Contact already exists" }), {
        status: 409,
      }),
    );

    const response = await POST(jsonRequest({ email: "ada@example.com" }));
    const payload = await response.json();

    expect(response.status).toBe(200);
    expect(payload.already_joined).toBe(true);
  });

  it("normalizes the email before sending it to the provider", async () => {
    fetchMock.mockResolvedValue(new Response("{}", { status: 201 }));

    await POST(jsonRequest({ email: "  Ada@Example.COM " }));

    expect(JSON.parse(fetchMock.mock.calls[0][1].body).email).toBe(
      "ada@example.com",
    );
  });

  it("rejects a malformed email without calling the provider", async () => {
    const response = await POST(jsonRequest({ email: "not-an-email" }));

    expect(response.status).toBe(422);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("rejects a missing body without calling the provider", async () => {
    const response = await POST(
      new Request("http://localhost/api/waitlist", { method: "POST" }),
    );

    expect(response.status).toBe(422);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("pretends success on a honeypot submission without calling the provider", async () => {
    const response = await POST(
      jsonRequest({ email: "bot@example.com", website: "https://spam.example" }),
    );
    const payload = await response.json();

    expect(response.status).toBe(201);
    expect(payload.already_joined).toBe(false);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("returns 502 when the provider fails, without leaking details", async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ message: "internal secret detail" }), {
        status: 500,
      }),
    );

    const response = await POST(jsonRequest({ email: "ada@example.com" }));
    const payload = await response.json();

    expect(response.status).toBe(502);
    expect(JSON.stringify(payload)).not.toContain("internal secret detail");
  });

  it("returns 502 when the collector is not configured", async () => {
    vi.stubEnv("RESEND_API_KEY", "");

    const response = await POST(jsonRequest({ email: "ada@example.com" }));

    expect(response.status).toBe(502);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("is inert once waitlist mode is off", async () => {
    vi.stubEnv("NEXT_PUBLIC_WAITLIST_MODE", "false");

    const response = await POST(jsonRequest({ email: "ada@example.com" }));

    expect(response.status).toBe(404);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
