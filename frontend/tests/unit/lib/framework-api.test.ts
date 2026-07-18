/**
 * Framework seller API adapter tests.
 *
 * Verifies that personal and organization identities route management actions
 * through the correct generated SDK operations and path parameters.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as sdk from "@/lib/generated/sdk.gen";
import { frameworkApiFor } from "@/lib/frameworks/framework-api";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: vi.fn(() => "Request failed"),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer token" })),
}));
vi.mock("@/lib/generated/sdk.gen");

beforeEach(() => {
  vi.resetAllMocks();
});

describe("frameworkApiFor", () => {
  it("binds the organization id when creating an org Framework", async () => {
    vi.mocked(sdk.createOrgFrameworkV1OrgsOrgIdFrameworksPost).mockResolvedValue({
      data: { id: "framework-1" },
    } as never);

    await frameworkApiFor({ kind: "org", orgId: "org-1" }).create({
      title: "Controls Handbook",
    } as never);

    expect(sdk.createOrgFrameworkV1OrgsOrgIdFrameworksPost).toHaveBeenCalledWith(
      expect.objectContaining({
        body: { title: "Controls Handbook" },
        path: { org_id: "org-1" },
      }),
    );
  });

  it("uses the dedicated organization pricing endpoint", async () => {
    vi.mocked(
      sdk.updateOrgFrameworkPricingV1OrgsOrgIdFrameworksFrameworkIdPricingPatch,
    ).mockResolvedValue({ data: { id: "framework-1" } } as never);

    await frameworkApiFor({ kind: "org", orgId: "org-1" }).updatePricing(
      "framework-1",
      { pricing: {} } as never,
    );

    expect(
      sdk.updateOrgFrameworkPricingV1OrgsOrgIdFrameworksFrameworkIdPricingPatch,
    ).toHaveBeenCalledWith(
      expect.objectContaining({
        body: { pricing: {} },
        path: { org_id: "org-1", framework_id: "framework-1" },
      }),
    );
  });

  it("updates personal pricing through the metadata patch endpoint", async () => {
    vi.mocked(sdk.updateFrameworkV1FrameworksFrameworkIdPatch).mockResolvedValue({
      data: { id: "framework-1" },
    } as never);

    await frameworkApiFor({ kind: "user" }).updatePricing("framework-1", {
      pricing: {},
    } as never);

    expect(sdk.updateFrameworkV1FrameworksFrameworkIdPatch).toHaveBeenCalledWith(
      expect.objectContaining({
        body: { pricing: {} },
        path: { framework_id: "framework-1" },
      }),
    );
  });

  it("binds both path ids when relisting an org Framework", async () => {
    vi.mocked(
      sdk.relistOrgFrameworkV1OrgsOrgIdFrameworksFrameworkIdRelistPost,
    ).mockResolvedValue({ data: { id: "framework-1" } } as never);

    await frameworkApiFor({ kind: "org", orgId: "org-1" }).relist(
      "framework-1",
    );

    expect(
      sdk.relistOrgFrameworkV1OrgsOrgIdFrameworksFrameworkIdRelistPost,
    ).toHaveBeenCalledWith(
      expect.objectContaining({
        path: { org_id: "org-1", framework_id: "framework-1" },
      }),
    );
  });
});
