import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const sdkPath = join(process.cwd(), "src/lib/generated/sdk.gen.ts");
const typesPath = join(process.cwd(), "src/lib/generated/types.gen.ts");
let sdk = readFileSync(sdkPath, "utf8");
let types = readFileSync(typesPath, "utf8");

if (!sdk.startsWith("// @ts-nocheck")) {
  sdk = `// @ts-nocheck\n${sdk}`;
}

const compatibilityAliases = {
  acceptArtifactRedaction: "acceptRedactionV1FrameworksFrameworkIdArtifactsArtifactIdAcceptRedactionPost",
  acceptAttestationOffer: "acceptAttestationOfferV1AttestationsAttestationIdAcceptPost",
  acceptAttestationReport: "acceptAttestationReportV1AttestationsAttestationIdAcceptReportPost",
  acceptProposal: "acceptProposalV1ProjectsProjectIdProposalsProposalIdAcceptPost",
  acknowledgeFrameworkSoftFail: "acknowledgeSoftFailV1FrameworksFrameworkIdAcknowledgeSoftFailPost",
  acknowledgeSimilarityNotice: "acknowledgeSimilarityNoticeV1FrameworksFrameworkIdSimilarityNoticeAcknowledgePost",
  adminAssignAttestation: "adminAssignAttestationV1AdminAttestationsAttestationIdAssignPost",
  adminRefundAttestation: "adminRefundAttestationV1AdminAttestationsAttestationIdRefundPost",
  approveDeliverable: "approveDeliverableV1ProjectsProjectIdMilestonesMilestoneIdDeliverablesDeliverableIdApprovePost",
  confirmArtifactUpload: "confirmArtifactUploadV1FrameworksFrameworkIdArtifactsConfirmPost",
  createAttestationDispute: "createAttestationDisputeV1AttestationsAttestationIdDisputesPost",
  createCredential: "createCredentialV1CredentialsPost",
  createCollection: "createCollectionV1CollectionsPost",
  createCollectionPurchase:
    "createCollectionPurchaseV1FinancialsCollectionsCollectionIdPurchasePost",
  createFramework: "createFrameworkV1FrameworksPost",
  createFrameworkPurchase: "createFrameworkPurchaseV1FinancialsPurchaseFrameworkIdPost",
  createFrameworkReview: "createFrameworkReviewV1FrameworksFrameworkIdReviewsPost",
  createFrameworkVersion: "createNewVersionV1FrameworksFrameworkIdVersionsPost",
  createMilestone: "createMilestoneV1ProjectsProjectIdMilestonesPost",
  createPaymentMethodSetup: "createPaymentMethodSetupV1FinancialsPaymentMethodsPost",
  createProject: "createProjectV1ProjectsPost",
  createWorkspaceMessage: "createWorkspaceMessageV1ProjectsProjectIdMessagesPost",
  declineAttestationOffer: "declineAttestationOfferV1AttestationsAttestationIdDeclinePost",
  deleteArtifact: "deleteArtifactV1FrameworksFrameworkIdArtifactsArtifactIdDelete",
  deleteCredential: "deleteCredentialV1CredentialsCredentialIdDelete",
  disableTotp: "disableTotpV1Auth2FaDisablePost",
  deletePaymentMethod: "deletePaymentMethodV1FinancialsPaymentMethodsPaymentMethodIdDelete",
  downloadLicensedArtifact: "downloadArtifactV1FrameworksFrameworkIdArtifactsArtifactIdDownloadGet",
  finalizeMilestonePlan: "finalizeMilestonePlanV1ProjectsProjectIdMilestonesFinalizePost",
  forgotPassword: "forgotPasswordV1AuthForgotPasswordPost",
  fundMilestone: "fundMilestoneV1ProjectsProjectIdMilestonesMilestoneIdFundPost",
  getContributorEarnings: "getContributorEarningsV1FinancialsEarningsGet",
  getContributorFramework: "getFrameworkV1FrameworksFrameworkIdGet",
  getCurrentUser: "meV1AuthMeGet",
  getExploreCollectionDetail: "getCollectionDetailV1ExploreCollectionsCollectionIdGet",
  getExploreContributorProfile: "getContributorProfileV1ExploreContributorsContributorIdGet",
  getExploreFrameworkDetail: "getFrameworkDetailV1ExploreFrameworksFrameworkIdGet",
  getFrameworkPurchaseInvoice: "getFrameworkPurchaseInvoiceV1FinancialsPurchasesTransactionIdInvoiceGet",
  getHealth: "getHealthV1HealthGet",
  getAccountDeletionStatus: "getAccountDeletionStatusV1GdprAccountDeletionGet",
  getProject: "getProjectV1ProjectsProjectIdGet",
  getRelatedExploreFrameworks: "getRelatedFrameworksV1ExploreFrameworksFrameworkIdRelatedGet",
  listAttestations: "listAttestationsV1AttestationsGet",
  listAttestorApplicationsForAdmin: "listAttestorApplicationsForAdminV1AdminAttestorApplicationsGet",
  listAttestorAssignments: "listAttestorAssignmentsV1AttestorAssignmentsGet",
  listContributorFrameworks: "listFrameworksV1FrameworksGet",
  listExploreCollections: "listCollectionsV1ExploreCollectionsGet",
  listCredentials: "listCredentialsV1CredentialsGet",
  listExploreFrameworks: "listFrameworksV1ExploreFrameworksGet",
  listExploreMixedCatalog: "listMixedCatalogV1ExploreCatalogGet",
  listFrameworkArtifacts: "listArtifactsV1FrameworksFrameworkIdArtifactsGet",
  listFrameworkPurchases: "listFrameworkPurchasesV1FinancialsPurchasesGet",
  listFrameworkReviews: "listFrameworkReviewsV1FrameworksFrameworkIdReviewsGet",
  listMilestones: "listMilestonesV1ProjectsProjectIdMilestonesGet",
  listMyAttestorApplications: "listMyAttestorApplicationsV1AttestorApplicationsMineGet",
  listMyCollections: "listMyCollectionsV1CollectionsMineGet",
  listMyProjectProposals: "listMyProjectProposalsV1ProjectsProjectIdProposalsMineGet",
  listOperatorLibrary: "listLibraryV1LibraryGet",
  listPaymentMethods: "listPaymentMethodsV1FinancialsPaymentMethodsGet",
  listPayoutAccounts: "listPayoutAccountsV1FinancialsPayoutAccountsGet",
  listPayouts: "listPayoutsV1FinancialsPayoutsGet",
  listProjectProposals: "listProjectProposalsV1ProjectsProjectIdProposalsGet",
  listProjects: "listProjectsV1ProjectsGet",
  listSessions: "listSessionsV1SettingsSessionsGet",
  listWorkspaceMessages: "listWorkspaceMessagesV1ProjectsProjectIdMessagesGet",
  login: "loginV1AuthLoginPost",
  onboardPayoutAccount: "onboardPayoutAccountV1FinancialsPayoutAccountsOnboardPost",
  publishFramework: "publishFrameworkV1FrameworksFrameworkIdPublishPost",
  refreshToken: "refreshV1AuthRefreshPost",
  regenerateBackupCodes: "regenerateBackupCodesV1Auth2FaBackupCodesRegeneratePost",
  refundFrameworkPurchase: "refundFrameworkPurchaseV1FinancialsPurchasesTransactionIdRefundPost",
  registerUser: "registerV1AuthRegisterPost",
  requestArtifactUploadUrl: "requestArtifactUploadUrlV1FrameworksFrameworkIdArtifactsUploadUrlPost",
  requestAttestation: "requestAttestationV1AttestationsPost",
  requestAccountDeletion: "requestAccountDeletionV1GdprAccountDeletionPost",
  requestEmailChange: "requestEmailChangeV1SettingsAccountEmailChangePost",
  requestKycUploadUrl: "requestKycUploadUrlV1SettingsKycUploadUrlPost",
  requestPayout: "requestPayoutV1FinancialsPayoutsPost",
  resetPassword: "resetPasswordV1AuthResetPasswordPost",
  resolveArtifactPiiReview: "resolvePiiReviewV1FrameworksFrameworkIdArtifactsArtifactIdResolvePiiReviewPost",
  resolveAttestationDispute: "resolveAttestationDisputeV1AdminAttestationDisputesDisputeIdResolvePost",
  reviewAttestorApplication: "reviewAttestorApplicationV1AdminAttestorApplicationsApplicationIdReviewPost",
  createSavedSearch: "createSavedSearchV1SavedSearchesPost",
  deleteSavedSearch: "deleteSavedSearchV1SavedSearchesSavedSearchIdDelete",
  listSavedSearches: "listSavedSearchesV1SavedSearchesGet",
  runSavedSearch: "runSavedSearchV1SavedSearchesSavedSearchIdRunGet",
  updateSavedSearch: "updateSavedSearchV1SavedSearchesSavedSearchIdPatch",
  cancelAccountDeletion: "cancelAccountDeletionV1GdprAccountDeletionCancelPost",
  revokeOtherSessions: "revokeOtherSessionsV1SettingsSessionsDelete",
  revokeSession: "revokeSessionV1SettingsSessionsSessionIdDelete",
  setupTotp: "setupTotpV1Auth2FaSetupPost",
  submitAttestationReport: "submitAttestationReportV1AttestationsAttestationIdReportPost",
  submitAttestorApplication: "submitAttestorApplicationV1AttestorApplicationsPost",
  submitDeliverable: "submitDeliverableV1ProjectsProjectIdMilestonesMilestoneIdDeliverablesPost",
  submitFramework: "submitFrameworkV1FrameworksFrameworkIdSubmitPost",
  submitKycUpload: "submitKycUploadV1SettingsKycSubmitPost",
  submitProposal: "submitProposalV1ProjectsProjectIdProposalsPost",
  totpStatus: "totpStatusV1Auth2FaStatusGet",
  unpublishFramework: "unpublishFrameworkV1FrameworksFrameworkIdUnpublishPost",
  updateFramework: "updateFrameworkV1FrameworksFrameworkIdPatch",
  updateMyFrameworkReview: "updateMyFrameworkReviewV1FrameworksFrameworkIdReviewsMePatch",
  verifyEmail: "verifyEmailV1AuthVerifyEmailPost",
  verifyTotp: "verifyTotpV1Auth2FaVerifyPost",
  verifyTotpLogin: "verifyTotpLoginV1Auth2FaVerifyLoginPost",
  withdrawAttestorApplication: "withdrawAttestorApplicationV1AttestorApplicationsApplicationIdWithdrawPatch",
};

const aliasBlock = [
  "",
  "// Compatibility aliases used by application code.",
  ...Object.entries(compatibilityAliases).map(
    ([alias, target]) => `export const ${alias} = ${target};`,
  ),
  "",
].join("\n");

if (!sdk.includes("// Compatibility aliases used by application code.")) {
  sdk = `${sdk.trimEnd()}\n${aliasBlock}`;
}

const manualSdkBlock = `
// Manually patched SDK functions for paths skipped by codegen.
export const getLatestDataExportStatusV1GdprExportsLatestGet = <ThrowOnError extends boolean = false>(options?: OptionsLegacyParser<unknown, ThrowOnError>) => {
  return (options?.client ?? client).get<any, any, ThrowOnError>({
    ...options,
    url: '/v1/gdpr/exports/latest'
  });
};
`;

if (!sdk.includes("getLatestDataExportStatusV1GdprExportsLatestGet")) {
  sdk = `${sdk.trimEnd()}\n${manualSdkBlock}`;
}

writeFileSync(sdkPath, sdk);

const typeAliasBlock = `
// Compatibility aliases used by application code.
export type ExploreAttestationStatus = ListFrameworksV1ExploreFrameworksGetData["query"] extends infer Query ? NonNullable<Query extends { attestation_status?: infer Value } ? Value : never> : never;
export type ExploreSort = NonNullable<NonNullable<ListFrameworksV1ExploreFrameworksGetData["query"]>["sort"]>;
export type FrameworkCategory = NonNullable<NonNullable<FrameworkCreate["category"]>>;
export type FrameworkSector = NonNullable<NonNullable<FrameworkUpdate["sector"]>>;
export type FrameworkIndustry = NonNullable<NonNullable<FrameworkUpdate["industry"]>>;
export type FrameworkFunction = NonNullable<NonNullable<FrameworkUpdate["function"]>>;
export type OrgSize = NonNullable<NonNullable<FrameworkUpdate["org_size"]>>;
export type ListExploreFrameworksData = ListFrameworksV1ExploreFrameworksGetData;
export type PricingConfig = PricingConfig_Output;
`;

if (!types.includes("// Compatibility aliases used by application code.")) {
  types = `${types.trimEnd()}\n${typeAliasBlock}`;
}

writeFileSync(typesPath, types);
