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

/** Friendly guidance shown when an organization member lacks contributor rights. */
export const CONTRIBUTOR_GRANT_REQUIRED_MESSAGE =
  "You need the Contributor right for this organization. Ask an admin to add you to a team with the Contributor capability.";

/** Safe API failure carrying a machine-readable backend error code. */
export class FrameworkApiError extends Error {
  /** Stable backend error code, when one was provided. */
  readonly code: string | undefined;

  /** Build a safe adapter error without retaining a raw response payload. */
  constructor(message: string, code?: string) {
    super(message);
    this.name = "FrameworkApiError";
    this.code = code;
  }
}

/** Determine whether an unknown failure has a specific Framework API code. */
export function isFrameworkApiErrorCode(
  error: unknown,
  code: string,
): boolean {
  return error instanceof FrameworkApiError && error.code === code;
}

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
  deleteArtifact(id: string, artifactId: string): Promise<void>;
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

/** Extract a stable code from FastAPI's structured HTTPException detail. */
function errorCode(error: unknown): string | undefined {
  if (!error || typeof error !== "object" || !("detail" in error)) {
    return undefined;
  }
  const { detail } = error as { detail: unknown };
  if (!detail || typeof detail !== "object" || !("error_code" in detail)) {
    return undefined;
  }
  const { error_code: code } = detail as { error_code: unknown };
  return typeof code === "string" ? code : undefined;
}

function authorizedHeaders(): ReturnType<typeof getAccessTokenHeaders> {
  configureBrowserClient();
  return getAccessTokenHeaders();
}

async function unwrap<T>(promise: Promise<ApiResult<T>>): Promise<T> {
  const { data, error } = await promise;
  if (data === undefined || error !== undefined) {
    throw new FrameworkApiError(
      describeGeneratedError(error),
      errorCode(error),
    );
  }
  return data;
}

/** Await a no-content (204) operation, raising a safe error on failure.
 *
 * Delete endpoints return an empty body, so `unwrap` cannot be used: its
 * `data === undefined` guard would treat a successful 204 as a failure.
 */
async function unwrapVoid(promise: Promise<ApiResult<unknown>>): Promise<void> {
  const { error } = await promise;
  if (error !== undefined) {
    throw new FrameworkApiError(
      describeGeneratedError(error),
      errorCode(error),
    );
  }
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
    deleteArtifact: (id, artifactId) =>
      unwrapVoid(
        sdk.deleteArtifactV1FrameworksFrameworkIdArtifactsArtifactIdDelete({
          headers: authorizedHeaders(),
          path: { framework_id: id, artifact_id: artifactId },
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
    deleteArtifact: (id, artifactId) =>
      unwrapVoid(
        sdk.deleteOrgFrameworkArtifactV1OrgsOrgIdFrameworksFrameworkIdArtifactsArtifactIdDelete(
          {
            headers: authorizedHeaders(),
            path: { ...orgPath, framework_id: id, artifact_id: artifactId },
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
