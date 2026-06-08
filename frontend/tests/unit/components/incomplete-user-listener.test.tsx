import { render, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { IncompleteUserListener } from "@/components/incomplete-user-listener";
import {
  INCOMPLETE_USER_EVENT,
  type IncompleteUserEventDetail,
} from "@/lib/auth/incomplete-user-events";

const push = vi.fn();
const installIncompleteUserInterceptor = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}));

vi.mock("@/lib/auth/incomplete-user-interceptor", () => ({
  installIncompleteUserInterceptor: () => installIncompleteUserInterceptor(),
}));

function dispatchIncompleteUser(detail: IncompleteUserEventDetail) {
  window.dispatchEvent(
    new CustomEvent<IncompleteUserEventDetail>(INCOMPLETE_USER_EVENT, {
      detail,
    }),
  );
}

describe("IncompleteUserListener", () => {
  beforeEach(() => {
    push.mockReset();
    installIncompleteUserInterceptor.mockReset();
    window.history.pushState(null, "", "/dashboard/frameworks/new");
  });

  it("routes incomplete users to onboarding with attempted intent and error code", async () => {
    render(<IncompleteUserListener />);

    dispatchIncompleteUser({
      attemptedPath: "/dashboard/frameworks/new",
      errorCode: "kyc_required",
      onboardingUrl: "/settings/onboarding",
    });

    await waitFor(() => {
      expect(push).toHaveBeenCalledWith(
        "/settings/onboarding?next=%2Fdashboard%2Fframeworks%2Fnew&error_code=kyc_required",
      );
    });
    expect(installIncompleteUserInterceptor).toHaveBeenCalledTimes(1);
  });

  it("does not redirect when already on onboarding", async () => {
    window.history.pushState(null, "", "/settings/onboarding");
    render(<IncompleteUserListener />);

    dispatchIncompleteUser({
      attemptedPath: "/dashboard/frameworks/new",
      errorCode: "kyc_required",
      onboardingUrl: "/settings/onboarding",
    });

    await waitFor(() => {
      expect(installIncompleteUserInterceptor).toHaveBeenCalledTimes(1);
    });
    expect(push).not.toHaveBeenCalled();
  });
});
