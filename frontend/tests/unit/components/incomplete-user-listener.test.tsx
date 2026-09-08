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

  it("sends a consent block to the page that can actually clear it", async () => {
    // Consent is not part of onboarding: that page has no way to accept new
    // legal versions, so routing there strands the user on a checklist reading
    // "Done" with a Continue button that walks straight back into the 403.
    render(<IncompleteUserListener />);

    dispatchIncompleteUser({
      attemptedPath: "/settings/roles",
      errorCode: "consent_required",
      onboardingUrl: "/settings/consent",
    });

    await waitFor(() => {
      expect(push).toHaveBeenCalledWith(
        "/settings/consent?next=%2Fsettings%2Froles&error_code=consent_required",
      );
    });
  });

  it("ignores a destination that would leave the origin", async () => {
    render(<IncompleteUserListener />);

    dispatchIncompleteUser({
      attemptedPath: "/dashboard/frameworks/new",
      errorCode: "kyc_required",
      onboardingUrl: "https://evil.example/onboarding",
    });

    await waitFor(() => {
      expect(push).toHaveBeenCalledWith(
        "/settings/onboarding?next=%2Fdashboard%2Fframeworks%2Fnew&error_code=kyc_required",
      );
    });
  });

  it("does not redirect when already on the destination surface", async () => {
    window.history.pushState(null, "", "/settings/consent");
    render(<IncompleteUserListener />);

    dispatchIncompleteUser({
      attemptedPath: "/settings/roles",
      errorCode: "consent_required",
      onboardingUrl: "/settings/consent",
    });

    await waitFor(() => {
      expect(installIncompleteUserInterceptor).toHaveBeenCalledTimes(1);
    });
    expect(push).not.toHaveBeenCalled();
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
