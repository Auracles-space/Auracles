import { beforeEach, describe, expect, it, vi } from "vitest";

import { installIncompleteUserInterceptor } from "@/lib/auth/incomplete-user-interceptor";
import { INCOMPLETE_USER_EVENT } from "@/lib/auth/incomplete-user-events";

const sdkMock = vi.hoisted(() => ({
  responseUse: vi.fn(),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  client: {
    interceptors: {
      response: {
        use: sdkMock.responseUse,
      },
    },
    setConfig: vi.fn(),
  },
}));

describe("incomplete-user interceptor", () => {
  beforeEach(() => {
    sdkMock.responseUse.mockClear();
    window.history.pushState(null, "", "/dashboard/frameworks/new?draft=1");
  });

  it("dispatches incomplete-user events without consuming the original response", async () => {
    installIncompleteUserInterceptor();
    const interceptor = sdkMock.responseUse.mock.calls[0]?.[0];
    expect(interceptor).toBeTypeOf("function");

    const dispatched = new Promise<CustomEvent>((resolve) => {
      window.addEventListener(
        INCOMPLETE_USER_EVENT,
        (event) => resolve(event as CustomEvent),
        { once: true },
      );
    });
    const response = new Response(
      JSON.stringify({
        detail: {
          error_code: "kyc_required",
          onboarding_url: "/settings/onboarding",
        },
      }),
      { status: 403 },
    );

    const returned = await interceptor(response);
    const event = await dispatched;

    expect(returned).toBe(response);
    expect(await response.json()).toEqual({
      detail: {
        error_code: "kyc_required",
        onboarding_url: "/settings/onboarding",
      },
    });
    expect(event.detail).toEqual({
      attemptedPath: "/dashboard/frameworks/new?draft=1",
      errorCode: "kyc_required",
      onboardingUrl: "/settings/onboarding",
    });
  });
});
