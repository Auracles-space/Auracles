import { describe, expect, it } from "vitest";

import {
  signSessionHintForTest,
  verifySessionHintCookie,
} from "@/lib/auth/session-hint-cookie";

describe("session hint cookie", () => {
  it("parses a valid signed session hint", async () => {
    const cookie = await signSessionHintForTest(
      {
        user_id: "user-123",
        roles: ["admin"],
        totp_verified: true,
        exp: Math.floor(Date.now() / 1000) + 60,
      },
      "test-secret",
    );

    await expect(verifySessionHintCookie(cookie, "test-secret")).resolves.toEqual({
      userId: "user-123",
      roles: ["admin"],
      totpVerified: true,
      expiresAt: expect.any(Number),
    });
  });

  it("rejects tampered or expired session hints", async () => {
    const valid = await signSessionHintForTest(
      {
        user_id: "user-123",
        roles: ["operator"],
        totp_verified: false,
        exp: Math.floor(Date.now() / 1000) + 60,
      },
      "test-secret",
    );
    const expired = await signSessionHintForTest(
      {
        user_id: "user-123",
        roles: ["operator"],
        totp_verified: false,
        exp: Math.floor(Date.now() / 1000) - 1,
      },
      "test-secret",
    );

    await expect(
      verifySessionHintCookie(`${valid}tampered`, "test-secret"),
    ).resolves.toBeNull();
    await expect(verifySessionHintCookie(expired, "test-secret")).resolves.toBeNull();
  });
});
