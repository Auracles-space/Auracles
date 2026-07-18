/**
 * Framework management API adapter.
 *
 * Provides one authenticated management surface for personal and organization
 * sellers so dashboard components do not depend on concrete generated routes.
 */
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import * as sdk from "@/lib/generated/sdk.gen";
import type {
  ArtifactConfirmRequest,
  ArtifactResponse,
  ArtifactUploadUrlRequest,
  ArtifactUploadUrlResponse,
  FrameworkCreate,
  FrameworkListItem,
  FrameworkMetadataUpdate,
  FrameworkPricingUpdate,
  FrameworkResponse,
  FrameworkUpdate,
  FrameworkVersionCreate,
} from "@/lib/generated/types.gen";

export type FrameworkSeller =
  | { kind: "user" }
  | { kind: "org"; orgId: string };

/** Uniform authenticated Framework management operations for one seller. */
export interface FrameworkApi {
  list(): Promise<FrameworkListItem[]>;
  get(id: string): Promise<FrameworkResponse>;
  create(body: FrameworkCreate): Promise<FrameworkResponse>;
  update(id: string, body: FrameworkUpdate): Promise<FrameworkResponse>;
  updatePricing(
    id: string,
    body: FrameworkPricingUpdate,
  ): Promise<FrameworkResponse>;
  startVersion(
    id: string,
    body: FrameworkVersionCreate,
  ): Promise<FrameworkResponse>;
  submit(id: string): Promise<FrameworkResponse>;
  publish(id: string): Promise<FrameworkResponse>;
  unpublish(id: string): Promise<FrameworkResponse>;
  relist(id: string): Promise<FrameworkResponse>;
  listArtifacts(id: string): Promise<ArtifactResponse[]>;
  createArtifactUpload(
    id: string,
    body: ArtifactUploadUrlRequest,
  ): Promise<ArtifactUploadUrlResponse>;
  confirmArtifact(
    id: string,
    artifactId: string,
    body: ArtifactConfirmRequest,
  ): Promise<ArtifactResponse>;
}

type ApiResult<T> = { data?: T; error?: unknown };

function authorizedHeaders(): ReturnType<typeof getAccessTokenHeaders> {
  configureBrowserClient();
  return getAccessTokenHeaders();
}

async function unwrap<T>(promise: Promise<ApiResult<T>>): Promise<T> {
  const { data, error } = await promise;
  if (data === undefined || error !== undefined) {
    throw new Error(describeGeneratedError(error));
  }
  return data;
}

function personalFrameworkApi(): FrameworkApi {
  return {
    list: () =>
      unwrap(
        sdk.listFrameworksV1FrameworksGet({ headers: authorizedHeaders() }),
      ),
    get: (id) =>
      unwrap(
        sdk.getFrameworkV1FrameworksFrameworkIdGet({
          headers: authorizedHeaders(),
          path: { framework_id: id },
        }),
      ),
    create: (body) =>
      unwrap(
        sdk.createFrameworkV1FrameworksPost({
          body,
          headers: authorizedHeaders(),
        }),
      ),
    update: (id, body) =>
      unwrap(
        sdk.updateFrameworkV1FrameworksFrameworkIdPatch({
          body,
          headers: authorizedHeaders(),
          path: { framework_id: id },
        }),
      ),
    updatePricing: (id, body) =>
      unwrap(
        sdk.updateFrameworkV1FrameworksFrameworkIdPatch({
          body,
          headers: authorizedHeaders(),
          path: { framework_id: id },
        }),
      ),
    startVersion: (id, body) =>
      unwrap(
        sdk.createNewVersionV1FrameworksFrameworkIdVersionsPost({
          body,
          headers: authorizedHeaders(),
          path: { framework_id: id },
        }),
      ),
    submit: (id) =>
      unwrap(
        sdk.submitFrameworkV1FrameworksFrameworkIdSubmitPost({
          headers: authorizedHeaders(),
          path: { framework_id: id },
        }),
      ),
    publish: (id) =>
      unwrap(
        sdk.publishFrameworkV1FrameworksFrameworkIdPublishPost({
          headers: authorizedHeaders(),
          path: { framework_id: id },
        }),
      ),
    unpublish: (id) =>
      unwrap(
        sdk.unpublishFrameworkV1FrameworksFrameworkIdUnpublishPost({
          headers: authorizedHeaders(),
          path: { framework_id: id },
        }),
      ),
    relist: (id) =>
      unwrap(
        sdk.relistFrameworkV1FrameworksFrameworkIdRelistPost({
          headers: authorizedHeaders(),
          path: { framework_id: id },
        }),
      ),
    listArtifacts: (id) =>
      unwrap(
        sdk.listArtifactsV1FrameworksFrameworkIdArtifactsGet({
          headers: authorizedHeaders(),
          path: { framework_id: id },
        }),
      ),
    createArtifactUpload: (id, body) =>
      unwrap(
        sdk.requestArtifactUploadUrlV1FrameworksFrameworkIdArtifactsUploadUrlPost(
          {
            body,
            headers: authorizedHeaders(),
            path: { framework_id: id },
          },
        ),
      ),
    confirmArtifact: (id, artifactId, body) =>
      unwrap(
        sdk.confirmArtifactUploadV1FrameworksFrameworkIdArtifactsConfirmPost({
          body: { ...body, artifact_id: artifactId },
          headers: authorizedHeaders(),
          path: { framework_id: id },
        }),
      ),
  };
}

function orgFrameworkApi(orgId: string): FrameworkApi {
  const orgPath = { org_id: orgId };
  return {
    list: () =>
      unwrap(
        sdk.listOrgFrameworksV1OrgsOrgIdFrameworksGet({
          headers: authorizedHeaders(),
          path: orgPath,
        }),
      ),
    get: (id) =>
      unwrap(
        sdk.getOrgFrameworkV1OrgsOrgIdFrameworksFrameworkIdGet({
          headers: authorizedHeaders(),
          path: { ...orgPath, framework_id: id },
        }),
      ),
    create: (body) =>
      unwrap(
        sdk.createOrgFrameworkV1OrgsOrgIdFrameworksPost({
          body,
          headers: authorizedHeaders(),
          path: orgPath,
        }),
      ),
    update: (id, body) => {
      const metadata = { ...body };
      delete metadata.pricing;
      return unwrap(
        sdk.updateOrgFrameworkV1OrgsOrgIdFrameworksFrameworkIdPatch({
          body: metadata as FrameworkMetadataUpdate,
          headers: authorizedHeaders(),
          path: { ...orgPath, framework_id: id },
        }),
      );
    },
    updatePricing: (id, body) =>
      unwrap(
        sdk.updateOrgFrameworkPricingV1OrgsOrgIdFrameworksFrameworkIdPricingPatch(
          {
            body,
            headers: authorizedHeaders(),
            path: { ...orgPath, framework_id: id },
          },
        ),
      ),
    startVersion: (id, body) =>
      unwrap(
        sdk.createNewOrgVersionV1OrgsOrgIdFrameworksFrameworkIdVersionPost({
          body,
          headers: authorizedHeaders(),
          path: { ...orgPath, framework_id: id },
        }),
      ),
    submit: (id) =>
      unwrap(
        sdk.submitOrgFrameworkV1OrgsOrgIdFrameworksFrameworkIdSubmitPost({
          headers: authorizedHeaders(),
          path: { ...orgPath, framework_id: id },
        }),
      ),
    publish: (id) =>
      unwrap(
        sdk.publishOrgFrameworkV1OrgsOrgIdFrameworksFrameworkIdPublishPost({
          headers: authorizedHeaders(),
          path: { ...orgPath, framework_id: id },
        }),
      ),
    unpublish: (id) =>
      unwrap(
        sdk.unpublishOrgFrameworkV1OrgsOrgIdFrameworksFrameworkIdUnpublishPost({
          headers: authorizedHeaders(),
          path: { ...orgPath, framework_id: id },
        }),
      ),
    relist: (id) =>
      unwrap(
        sdk.relistOrgFrameworkV1OrgsOrgIdFrameworksFrameworkIdRelistPost({
          headers: authorizedHeaders(),
          path: { ...orgPath, framework_id: id },
        }),
      ),
    listArtifacts: (id) =>
      unwrap(
        sdk.listOrgFrameworkArtifactsV1OrgsOrgIdFrameworksFrameworkIdArtifactsGet(
          {
            headers: authorizedHeaders(),
            path: { ...orgPath, framework_id: id },
          },
        ),
      ),
    createArtifactUpload: (id, body) =>
      unwrap(
        sdk.requestOrgArtifactUploadUrlV1OrgsOrgIdFrameworksFrameworkIdArtifactsUploadUrlPost(
          {
            body,
            headers: authorizedHeaders(),
            path: { ...orgPath, framework_id: id },
          },
        ),
      ),
    confirmArtifact: (id, artifactId, body) =>
      unwrap(
        sdk.confirmOrgArtifactUploadV1OrgsOrgIdFrameworksFrameworkIdArtifactsConfirmPost(
          {
            body: { ...body, artifact_id: artifactId },
            headers: authorizedHeaders(),
            path: { ...orgPath, framework_id: id },
          },
        ),
      ),
  };
}

/** Return an API adapter bound to the supplied seller identity. */
export function frameworkApiFor(seller: FrameworkSeller): FrameworkApi {
  return seller.kind === "org"
    ? orgFrameworkApi(seller.orgId)
    : personalFrameworkApi();
}
