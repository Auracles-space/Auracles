import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SoftFailAcknowledgement } from "@/components/modules/frameworks/soft-fail-acknowledgement";
import { FrameworkApiError } from "@/lib/frameworks/framework-api";
import type { FrameworkApi } from "@/lib/frameworks/framework-api";

/** Build a Framework API adapter double exposing only the soft-fail action. */
function makeApi(overrides: Partial<FrameworkApi> = {}): FrameworkApi {
  return {
    acknowledgeSoftFail: vi.fn().mockResolvedValue({ id: "fw_1" }),
    ...overrides,
  } as unknown as FrameworkApi;
}

describe("SoftFailAcknowledgement", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("acknowledges through the seller adapter, then reloads the workspace", async () => {
    const api = makeApi();
    const onAcknowledged = vi.fn();

    render(
      <SoftFailAcknowledgement
        api={api}
        frameworkId="fw_1"
        onAcknowledged={onAcknowledged}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /acknowledge soft fail/i }));

    await waitFor(() => {
      expect(api.acknowledgeSoftFail).toHaveBeenCalledWith("fw_1");
    });
    expect(onAcknowledged).toHaveBeenCalled();
  });

  it("surfaces a failure without reloading", async () => {
    const api = makeApi({
      acknowledgeSoftFail: vi
        .fn()
        .mockRejectedValue(new FrameworkApiError("Only failed checks can be acknowledged.")),
    });
    const onAcknowledged = vi.fn();

    render(
      <SoftFailAcknowledgement
        api={api}
        frameworkId="fw_1"
        onAcknowledged={onAcknowledged}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /acknowledge soft fail/i }));

    await waitFor(() => {
      expect(
        screen.getByText(/only failed checks can be acknowledged/i),
      ).toBeInTheDocument();
    });
    expect(onAcknowledged).not.toHaveBeenCalled();
  });
});
