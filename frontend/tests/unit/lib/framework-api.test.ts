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
  vi.clearAllMocks();
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

  it("deletes an org artifact through the organization delete endpoint", async () => {
    // A 204 has no body: data and error are both undefined. unwrapVoid must
    // treat this as success rather than a missing-data failure.
    vi.mocked(
      sdk.deleteOrgFrameworkArtifactV1OrgsOrgIdFrameworksFrameworkIdArtifactsArtifactIdDelete,
    ).mockResolvedValue({
      data: undefined,
      error: undefined,
      response: new Response(null, { status: 204 }),
    } as never);

    await expect(
      frameworkApiFor({ kind: "org", orgId: "org-1" }).deleteArtifact(
        "framework-1",
        "artifact-1",
      ),
    ).resolves.toBeUndefined();

    expect(
      sdk.deleteOrgFrameworkArtifactV1OrgsOrgIdFrameworksFrameworkIdArtifactsArtifactIdDelete,
    ).toHaveBeenCalledWith(
      expect.objectContaining({
        path: {
          org_id: "org-1",
          framework_id: "framework-1",
          artifact_id: "artifact-1",
        },
      }),
    );
  });

  it("deletes a personal artifact through the personal delete endpoint", async () => {
    vi.mocked(
      sdk.deleteArtifactV1FrameworksFrameworkIdArtifactsArtifactIdDelete,
    ).mockResolvedValue({
      data: undefined,
      error: undefined,
      response: new Response(null, { status: 204 }),
    } as never);

    await frameworkApiFor({ kind: "user" }).deleteArtifact(
      "framework-1",
      "artifact-1",
    );

    expect(
      sdk.deleteArtifactV1FrameworksFrameworkIdArtifactsArtifactIdDelete,
    ).toHaveBeenCalledWith(
      expect.objectContaining({
        path: { framework_id: "framework-1", artifact_id: "artifact-1" },
      }),
    );
  });

  it("raises a safe error when an artifact delete fails", async () => {
    vi.mocked(
      sdk.deleteOrgFrameworkArtifactV1OrgsOrgIdFrameworksFrameworkIdArtifactsArtifactIdDelete,
    ).mockResolvedValue({
      error: { detail: { error_code: "capability_grant_required" } },
      response: new Response(null, { status: 403 }),
    } as never);

    await expect(
      frameworkApiFor({ kind: "org", orgId: "org-1" }).deleteArtifact(
        "framework-1",
        "artifact-1",
      ),
    ).rejects.toMatchObject({ code: "capability_grant_required" });
  });

  it("sets an org preview through the organization preview endpoint", async () => {
    vi.mocked(
      sdk.setOrgFrameworkPreviewArtifactV1OrgsOrgIdFrameworksFrameworkIdPreviewArtifactPatch,
    ).mockResolvedValue({
      data: { id: "framework-1", preview_artifact_id: "artifact-1" },
      error: undefined,
      response: new Response(null, { status: 200 }),
    } as never);

    await frameworkApiFor({ kind: "org", orgId: "org-1" }).setPreviewArtifact(
      "framework-1",
      "artifact-1",
    );

    expect(
      sdk.setOrgFrameworkPreviewArtifactV1OrgsOrgIdFrameworksFrameworkIdPreviewArtifactPatch,
    ).toHaveBeenCalledWith(
      expect.objectContaining({
        body: { artifact_id: "artifact-1" },
        path: { org_id: "org-1", framework_id: "framework-1" },
      }),
    );
  });

  it("sets a personal preview through the personal preview endpoint", async () => {
    vi.mocked(
      sdk.setPreviewArtifactV1FrameworksFrameworkIdPreviewArtifactPatch,
    ).mockResolvedValue({
      data: { id: "framework-1", preview_artifact_id: "artifact-1" },
      error: undefined,
      response: new Response(null, { status: 200 }),
    } as never);

    await frameworkApiFor({ kind: "user" }).setPreviewArtifact(
      "framework-1",
      "artifact-1",
    );

    expect(
      sdk.setPreviewArtifactV1FrameworksFrameworkIdPreviewArtifactPatch,
    ).toHaveBeenCalledWith(
      expect.objectContaining({
        body: { artifact_id: "artifact-1" },
        path: { framework_id: "framework-1" },
      }),
    );
  });

  it("resolves org PII review through the organization endpoint", async () => {
    vi.mocked(
      sdk.resolveOrgFrameworkPiiReviewV1OrgsOrgIdFrameworksFrameworkIdArtifactsArtifactIdResolvePiiReviewPost,
    ).mockResolvedValue({
      data: { id: "artifact-1" },
      error: undefined,
      response: new Response(null, { status: 200 }),
    } as never);

    await frameworkApiFor({ kind: "org", orgId: "org-1" }).resolvePiiReview(
      "framework-1",
      "artifact-1",
    );

    expect(
      sdk.resolveOrgFrameworkPiiReviewV1OrgsOrgIdFrameworksFrameworkIdArtifactsArtifactIdResolvePiiReviewPost,
    ).toHaveBeenCalledWith(
      expect.objectContaining({
        path: {
          org_id: "org-1",
          framework_id: "framework-1",
          artifact_id: "artifact-1",
        },
      }),
    );
  });

  it("accepts an org redaction through the organization endpoint", async () => {
    vi.mocked(
      sdk.acceptOrgFrameworkRedactionV1OrgsOrgIdFrameworksFrameworkIdArtifactsArtifactIdAcceptRedactionPost,
    ).mockResolvedValue({
      data: { id: "artifact-1" },
      error: undefined,
      response: new Response(null, { status: 200 }),
    } as never);

    await frameworkApiFor({ kind: "org", orgId: "org-1" }).acceptRedaction(
      "framework-1",
      "artifact-1",
    );

    expect(
      sdk.acceptOrgFrameworkRedactionV1OrgsOrgIdFrameworksFrameworkIdArtifactsArtifactIdAcceptRedactionPost,
    ).toHaveBeenCalledWith(
      expect.objectContaining({
        path: {
          org_id: "org-1",
          framework_id: "framework-1",
          artifact_id: "artifact-1",
        },
      }),
    );
  });

  it("acknowledges an org soft fail through the organization endpoint", async () => {
    vi.mocked(
      sdk.acknowledgeOrgFrameworkSoftFailV1OrgsOrgIdFrameworksFrameworkIdAcknowledgeSoftFailPost,
    ).mockResolvedValue({
      data: { id: "framework-1", status: "pipeline_passed" },
      error: undefined,
      response: new Response(null, { status: 200 }),
    } as never);

    await frameworkApiFor({ kind: "org", orgId: "org-1" }).acknowledgeSoftFail(
      "framework-1",
    );

    expect(
      sdk.acknowledgeOrgFrameworkSoftFailV1OrgsOrgIdFrameworksFrameworkIdAcknowledgeSoftFailPost,
    ).toHaveBeenCalledWith(
      expect.objectContaining({
        path: { org_id: "org-1", framework_id: "framework-1" },
      }),
    );
  });

  it("acknowledges an org similarity notice through the organization endpoint", async () => {
    vi.mocked(
      sdk.acknowledgeOrgFrameworkSimilarityNoticeV1OrgsOrgIdFrameworksFrameworkIdSimilarityNoticeAcknowledgePost,
    ).mockResolvedValue({
      data: { id: "framework-1", status: "pipeline_passed" },
      error: undefined,
      response: new Response(null, { status: 200 }),
    } as never);

    await frameworkApiFor({
      kind: "org",
      orgId: "org-1",
    }).acknowledgeSimilarityNotice("framework-1", "Distinct sector focus.");

    expect(
      sdk.acknowledgeOrgFrameworkSimilarityNoticeV1OrgsOrgIdFrameworksFrameworkIdSimilarityNoticeAcknowledgePost,
    ).toHaveBeenCalledWith(
      expect.objectContaining({
        body: { differentiation_note: "Distinct sector focus." },
        path: { org_id: "org-1", framework_id: "framework-1" },
      }),
    );
  });

  it("acknowledges a personal soft fail through the personal endpoint", async () => {
    vi.mocked(sdk.acknowledgeFrameworkSoftFail).mockResolvedValue({
      data: { id: "framework-1", status: "pipeline_passed" },
      error: undefined,
      response: new Response(null, { status: 200 }),
    } as never);

    await frameworkApiFor({ kind: "user" }).acknowledgeSoftFail("framework-1");

    expect(sdk.acknowledgeFrameworkSoftFail).toHaveBeenCalledWith(
      expect.objectContaining({ path: { framework_id: "framework-1" } }),
    );
  });

  it("resolves personal PII review through the personal endpoint", async () => {
    vi.mocked(sdk.resolveArtifactPiiReview).mockResolvedValue({
      data: { id: "artifact-1" },
      error: undefined,
      response: new Response(null, { status: 200 }),
    } as never);

    await frameworkApiFor({ kind: "user" }).resolvePiiReview(
      "framework-1",
      "artifact-1",
    );

    expect(sdk.resolveArtifactPiiReview).toHaveBeenCalledWith(
      expect.objectContaining({
        path: { framework_id: "framework-1", artifact_id: "artifact-1" },
      }),
    );
  });

  it("preserves a backend capability grant denial as a safe error code", async () => {
    vi.mocked(
      sdk.listOrgFrameworksV1OrgsOrgIdFrameworksGet,
    ).mockResolvedValue({
      error: {
        detail: { error_code: "capability_grant_required" },
      },
      response: new Response(null, { status: 403 }),
    } as never);

    await expect(
      frameworkApiFor({ kind: "org", orgId: "org-1" }).list(),
    ).rejects.toMatchObject({
      code: "capability_grant_required",
      message: "Request failed",
    });
  });
});
