import { afterEach, describe, expect, it } from "vitest";

import {
  authTokenStore,
  clearAuthToken,
  setAccessTokenFromJwt,
} from "@/lib/auth/token-store";

function jwtWithPayload(payload: Record<string, unknown>) {
  const encodedPayload = Buffer.from(JSON.stringify(payload)).toString("base64url");
  return `header.${encodedPayload}.signature`;
}

describe("auth token store", () => {
  afterEach(() => {
    clearAuthToken();
  });

  it("derives public auth state from an access token", () => {
    const token = jwtWithPayload({
      sub: "user-123",
      roles: ["operator"],
      totp_verified: true,
      exp: 1_800_000_000,
    });

    setAccessTokenFromJwt(token);

    expect(authTokenStore.getState()).toMatchObject({
      accessToken: token,
      userId: "user-123",
      roles: ["operator"],
      totpVerified: true,
      expiresAt: 1_800_000_000,
    });
  });

  it("clears auth state", () => {
    setAccessTokenFromJwt(
      jwtWithPayload({
        sub: "user-123",
        roles: ["admin"],
        totp_verified: false,
        exp: 1_800_000_000,
      }),
    );

    clearAuthToken();

    expect(authTokenStore.getState()).toMatchObject({
      accessToken: null,
      userId: null,
      roles: [],
      totpVerified: false,
      expiresAt: null,
    });
  });
});
