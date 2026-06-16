import { beforeEach, describe, expect, it, vi } from "vitest";

import { refreshAccessToken } from "@/lib/auth/refresh-client";
import { refreshToken as generatedRefreshToken } from "@/lib/generated/sdk.gen";

vi.mock("@/lib/generated/sdk.gen", () => ({
  client: { setConfig: vi.fn() },
  refreshToken: vi.fn(),
}));

vi.mock("@/lib/auth/token-store", () => ({
  clearAuthToken: vi.fn(),
  setAccessTokenFromJwt: vi.fn(),
}));

describe("refreshAccessToken", () => {
  beforeEach(() => {
    vi.mocked(generatedRefreshToken).mockReset();
  });

  it("single-flights concurrent calls into one network request", async () => {
    // Without single-flight, two callers reuse the same refresh cookie and the
    // backend revokes the token family as a reuse attack -> session bounce.
    vi.mocked(generatedRefreshToken).mockImplementation(
      () =>
        new Promise((resolve) =>
          setTimeout(
            () =>
              resolve({
                data: { access_token: "header.payload.sig" },
                error: undefined,
                response: new Response(null, { status: 200 }),
              } as Awaited<ReturnType<typeof generatedRefreshToken>>),
            10,
          ),
        ),
    );

    const [a, b] = await Promise.all([
      refreshAccessToken(),
      refreshAccessToken(),
    ]);

    expect(a).toBe(true);
    expect(b).toBe(true);
    expect(vi.mocked(generatedRefreshToken)).toHaveBeenCalledTimes(1);
  });

  it("issues a fresh request after the previous one settles", async () => {
    vi.mocked(generatedRefreshToken).mockResolvedValue({
      data: { access_token: "header.payload.sig" },
      error: undefined,
      response: new Response(null, { status: 200 }),
    } as Awaited<ReturnType<typeof generatedRefreshToken>>);

    await refreshAccessToken();
    await refreshAccessToken();

    expect(vi.mocked(generatedRefreshToken)).toHaveBeenCalledTimes(2);
  });
});
