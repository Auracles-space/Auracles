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
  createDispute: "createDisputeV1ProjectsProjectIdDisputesPost",
  listDisputes: "listDisputesV1ProjectsProjectIdDisputesGet",
  createCollection: "createCollectionV1CollectionsPost",
  createCollectionPurchase:
    "createCollectionPurchaseV1FinancialsCollectionsCollectionIdPurchasePost",
  createFramework: "createFrameworkV1FrameworksPost",
  createFrameworkPurchase: "createFrameworkPurchaseV1FinancialsPurchaseFrameworkIdPost",
  createFrameworkReview: "createFrameworkReviewV1FrameworksFrameworkIdReviewsPost",
  createFrameworkVersion: "createNewVersionV1FrameworksFrameworkIdVersionsPost",
  cancelAcceptance: "cancelAcceptanceV1ProjectsProjectIdCancelAcceptancePost",
  cancelOrgAcceptance: "cancelOrgAcceptanceV1OrgsOrgIdProjectsProjectIdCancelAcceptancePost",
  createMilestone: "createMilestoneV1ProjectsProjectIdMilestonesPost",
  createPaymentMethodSetup: "createPaymentMethodSetupV1FinancialsPaymentMethodsPost",
  createProject: "createProjectV1ProjectsPost",
  listOrgProjects: "listOrgProjectsV1OrgsOrgIdProjectsGet",
  createWorkspaceMessage: "createWorkspaceMessageV1ProjectsProjectIdMessagesPost",
  createWorkspaceUploadSession: "createWorkspaceUploadSessionV1ProjectsProjectIdMessagesUploadsPost",
  deleteArtifact: "deleteArtifactV1FrameworksFrameworkIdArtifactsArtifactIdDelete",
  deleteCredential: "deleteCredentialV1CredentialsCredentialIdDelete",
  deleteMilestone: "deleteMilestoneV1ProjectsProjectIdMilestonesMilestoneIdDelete",
  deleteProject: "deleteProjectV1ProjectsProjectIdDelete",
  deleteOrgProject: "deleteOrgProjectV1OrgsOrgIdProjectsProjectIdDelete",
  disableTotp: "disableTotpV1Auth2FaDisablePost",
  deletePaymentMethod: "deletePaymentMethodV1FinancialsPaymentMethodsPaymentMethodIdDelete",
  downloadLicensedArtifact: "downloadArtifactV1FrameworksFrameworkIdArtifactsArtifactIdDownloadGet",
  finalizeMilestonePlan: "finalizeMilestonePlanV1ProjectsProjectIdMilestonesFinalizePost",
  reopenMilestonePlan: "reopenMilestonePlanV1ProjectsProjectIdMilestonesReopenPost",
  requestDeliverableRevision: "requestDeliverableRevisionV1ProjectsProjectIdMilestonesMilestoneIdDeliverablesDeliverableIdRequestRevisionPost",
  requestOrgDeliverableRevision: "requestOrgDeliverableRevisionV1OrgsOrgIdProjectsProjectIdMilestonesMilestoneIdDeliverablesDeliverableIdRequestRevisionPost",
  forgotPassword: "forgotPasswordV1AuthForgotPasswordPost",
  fundMilestone: "fundMilestoneV1ProjectsProjectIdMilestonesMilestoneIdFundPost",
  getAttestationFeePayment: "getAttestationFeePaymentV1AttestationsAttestationIdPaymentGet",
  getAdminAttestationDetail: "getAdminAttestationDetailV1AdminAttestationsAttestationIdGet",
  listAdminAttestations: "listAdminAttestationsV1AdminAttestationsGet",
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
  getOrgProject: "getOrgProjectV1OrgsOrgIdProjectsProjectIdGet",
  getRelatedExploreFrameworks: "getRelatedFrameworksV1ExploreFrameworksFrameworkIdRelatedGet",
  listAttestations: "listAttestationsV1AttestationsGet",
  listContributorFrameworks: "listFrameworksV1FrameworksGet",
  listExploreCollections: "listCollectionsV1ExploreCollectionsGet",
  listCredentials: "listCredentialsV1CredentialsGet",
  listExploreFrameworks: "listFrameworksV1ExploreFrameworksGet",
  listExploreMixedCatalog: "listMixedCatalogV1ExploreCatalogGet",
  listFrameworkArtifacts: "listArtifactsV1FrameworksFrameworkIdArtifactsGet",
  listFrameworkPurchases: "listFrameworkPurchasesV1FinancialsPurchasesGet",
  listFrameworkReviews: "listFrameworkReviewsV1FrameworksFrameworkIdReviewsGet",
  listDeliverables: "listDeliverablesV1ProjectsProjectIdMilestonesMilestoneIdDeliverablesGet",
  downloadDeliverableFiles: "downloadDeliverableFilesV1ProjectsProjectIdMilestonesMilestoneIdDeliverablesDeliverableIdDownloadGet",
  listMilestones: "listMilestonesV1ProjectsProjectIdMilestonesGet",
  listMyCollections: "listMyCollectionsV1CollectionsMineGet",
  listMyProjectProposals: "listMyProjectProposalsV1ProjectsProjectIdProposalsMineGet",
  listOperatorLibrary: "listLibraryV1LibraryGet",
  listPaymentMethods: "listPaymentMethodsV1FinancialsPaymentMethodsGet",
  listPayoutAccounts: "listPayoutAccountsV1FinancialsPayoutAccountsGet",
  listPayouts: "listPayoutsV1FinancialsPayoutsGet",
  listProjectProposals: "listProjectProposalsV1ProjectsProjectIdProposalsGet",
  listOrgProjectProposals: "listOrgProjectProposalsV1OrgsOrgIdProjectsProjectIdProposalsGet",
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
  relistFramework: "relistFrameworkV1FrameworksFrameworkIdRelistPost",
  requestPayout: "requestPayoutV1FinancialsPayoutsPost",
  resetPassword: "resetPasswordV1AuthResetPasswordPost",
  resolveArtifactPiiReview: "resolvePiiReviewV1FrameworksFrameworkIdArtifactsArtifactIdResolvePiiReviewPost",
  resolveAttestationDispute: "resolveAttestationDisputeV1AdminAttestationDisputesDisputeIdResolvePost",
  listAdminProjectDisputes: "listProjectDisputesV1AdminProjectsDisputesGet",
  resolveAdminProjectDispute: "resolveProjectDisputeV1AdminProjectsDisputesDisputeIdResolvePost",
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
  submitDeliverable: "submitDeliverableV1ProjectsProjectIdMilestonesMilestoneIdDeliverablesPost",
  submitFramework: "submitFrameworkV1FrameworksFrameworkIdSubmitPost",
  submitProposal: "submitProposalV1ProjectsProjectIdProposalsPost",
  totpStatus: "totpStatusV1Auth2FaStatusGet",
  unpublishFramework: "unpublishFrameworkV1FrameworksFrameworkIdUnpublishPost",
  updateFramework: "updateFrameworkV1FrameworksFrameworkIdPatch",
  updateMilestone: "updateMilestoneV1ProjectsProjectIdMilestonesMilestoneIdPatch",
  updateMyFrameworkReview: "updateMyFrameworkReviewV1FrameworksFrameworkIdReviewsMePatch",
  verifyEmail: "verifyEmailV1AuthVerifyEmailPost",
  verifyTotp: "verifyTotpV1Auth2FaVerifyPost",
  verifyTotpLogin: "verifyTotpLoginV1Auth2FaVerifyLoginPost",
  getOrgAttestorApplication: "getAttestorApplicationV1OrgsOrgIdAttestorApplicationGet",
  createOrgAttestorApplication: "createAttestorApplicationV1OrgsOrgIdAttestorApplicationPost",
  updateOrgAttestorApplication: "updateAttestorApplicationV1OrgsOrgIdAttestorApplicationPatch",
  submitOrgAttestorApplication: "submitAttestorApplicationV1OrgsOrgIdAttestorApplicationSubmitPost",
  signOrgAttestorUndertakings: "signAttestorUndertakingsV1OrgsOrgIdAttestorApplicationSignUndertakingsPost",
  uploadOrgAttestorTaxDocument: "setAttestorTaxDocumentV1OrgsOrgIdAttestorApplicationTaxDocumentPost",
  nominateOrgAttestorTrialMember: "nominateAttestorTrialMemberV1OrgsOrgIdAttestorApplicationNominateTrialMemberPost",
  listOrgAttestationOffers: "listOrgAttestationOffersV1OrgsOrgIdAttestationOffersGet",
  acceptOrgAttestationOffer: "acceptOrgAttestationOfferV1OrgsOrgIdAttestationOffersOfferIdAcceptPost",
  declineOrgAttestationOffer: "declineOrgAttestationOfferV1OrgsOrgIdAttestationOffersOfferIdDeclinePost",
  listOrgAttestations: "listOrgAttestationsV1OrgsOrgIdAttestationsGet",
  reassignOrgAttestation: "reassignOrgReviewingMemberV1OrgsOrgIdAttestationsAttestationIdReassignPost",
  getOrgNda: "getNdaStatusV1OrgsOrgIdNdaGet",
  signOrgNda: "signNdaV1OrgsOrgIdNdaSignPost",
  getOrgAttestorEarnings: "getOrgEarningsV1OrgsOrgIdFinancialsEarningsGet",
  onboardOrgPayoutAccount: "onboardOrgPayoutAccountV1OrgsOrgIdFinancialsPayoutAccountsPost",
  requestOrgPayout: "requestOrgPayoutV1OrgsOrgIdFinancialsPayoutsPost",
  listOrgInvoices: "listOrgInvoicesV1OrgsOrgIdFinancialsInvoicesGet",
  listOrgAttestorApplicationsForAdmin: "adminListOrgAttestorApplicationsV1AdminOrgAttestorApplicationsGet",
  listOrgAttestorDocumentsForAdmin: "adminListOrgAttestorDocumentsV1AdminOrgAttestorApplicationsApplicationIdDocumentsGet",
  verifyOrgAttestorKyb: "adminVerifyKybV1AdminOrgAttestorApplicationsApplicationIdVerifyKybPost",
  orgAttestorNeedsInfo: "adminNeedsInfoV1AdminOrgAttestorApplicationsApplicationIdNeedsInfoPost",
  startOrgAttestorTrial: "adminStartTrialV1AdminOrgAttestorApplicationsApplicationIdStartTrialPost",
  approveOrgAttestor: "adminApproveV1AdminOrgAttestorApplicationsApplicationIdApprovePost",
  rejectOrgAttestor: "adminRejectV1AdminOrgAttestorApplicationsApplicationIdRejectPost",
  suspendOrgAttestorCapability: "adminSuspendAttestorCapabilityV1AdminOrgsOrgIdAttestorCapabilitySuspendPost",
  reinstateOrgAttestorCapability: "adminReinstateAttestorCapabilityV1AdminOrgsOrgIdAttestorCapabilityReinstatePost",
  revokeOrgAttestorCapability: "adminRevokeAttestorCapabilityV1AdminOrgsOrgIdAttestorCapabilityRevokePost",
  listAttestorOrgs: "listPublicAttestorDirectoryV1AttestorOrgsGet",
  getAttestorOrg: "getPublicAttestorDirectoryProfileV1AttestorOrgsOrgIdGet",
  listAttestorOrgCompleted: "listAttestorCompletedAttestationsV1AttestorOrgsOrgIdCompletedGet",
  readPlatformConfig: "listPlatformConfigV1AdminConfigGet",
  updatePlatformConfig: "updatePlatformConfigV1AdminConfigPatch",
  getAttestation: "getAttestationV1AttestationsAttestationIdGet",
  startAttestationReview: "startAttestationReviewV1AttestationsAttestationIdStartReviewPost",
  giveAttestationConsent: "decideOwnerConsentV1AttestationsAttestationIdConsentPost",
  ackAttestationContent: "acknowledgeAttestationContentV1AttestationsAttestationIdContentAckPost",
  getAttestationArtifactAccess: "requestAttestationArtifactAccessV1AttestationsAttestationIdArtifactsArtifactIdAccessPost",
  getAttestationPackage: "getAttestationPackageV1AttestationsAttestationIdPackageGet",
  upsertRubricScore: "upsertAttestationRubricScoreV1AttestationsAttestationIdRubricDimensionKeyPut",
  listRubricScores: "listAttestationRubricScoresV1AttestationsAttestationIdRubricGet",
  getReportRubric: "getReportRubricV1AttestationsAttestationIdReportRubricGet",
  listAttestationAnnotations: "listAttestationAnnotationsV1AttestationsAttestationIdAnnotationsGet",
  createAttestationAnnotation: "createAttestationAnnotationV1AttestationsAttestationIdAnnotationsPost",
  updateAttestationAnnotation: "updateAttestationAnnotationV1AttestationsAttestationIdAnnotationsAnnotationIdPatch",
  deleteAttestationAnnotation: "deleteAttestationAnnotationV1AttestationsAttestationIdAnnotationsAnnotationIdDelete",
  listAttestationClarifications: "listAttestationClarificationsV1AttestationsAttestationIdClarificationsGet",
  createAttestationClarification: "createAttestationClarificationV1AttestationsAttestationIdClarificationsPost",
  respondAttestationClarification: "respondToAttestationClarificationV1AttestationsAttestationIdClarificationsClarificationIdRespondPost",
  markClarificationsSeen: "markAttestationClarificationsSeenV1AttestationsAttestationIdClarificationsMarkSeenPost",
  createAttestationEvidenceUpload: "createAttestationReportEvidenceUploadSessionV1AttestationsAttestationIdUploadsPost",
  createOrgFrameworkPurchase: "createOrgFrameworkPurchaseV1OrgsOrgIdFrameworksFrameworkIdPurchasePost",
  listOrgLibrary: "listOrgLibraryV1OrgsOrgIdLibraryGet",
  requestOrgLibraryArtifactDownload: "requestOrgLibraryArtifactDownloadV1OrgsOrgIdLibraryLicenseIdArtifactsArtifactIdDownloadPost",
  listOrgLicenseGrants: "listOrgLicenseGrantsV1OrgsOrgIdLicensesLicenseIdGrantsGet",
  addOrgLicenseGrant: "addOrgLicenseGrantV1OrgsOrgIdLicensesLicenseIdGrantsPost",
  revokeOrgLicenseGrant: "revokeOrgLicenseGrantV1OrgsOrgIdLicensesLicenseIdGrantsGrantIdDelete",
  createOrgPaymentMethodSetup: "createOrgPaymentMethodSetupV1OrgsOrgIdFinancialsPaymentMethodsSetupPost",
  listOrgPaymentMethods: "listOrgPaymentMethodsV1OrgsOrgIdFinancialsPaymentMethodsGet",
  deleteOrgPaymentMethod: "deleteOrgPaymentMethodV1OrgsOrgIdFinancialsPaymentMethodsPaymentMethodIdDelete",
  getOrgPurchaseInvoice: "getOrgPurchaseInvoiceV1OrgsOrgIdFinancialsPurchasesTransactionIdInvoiceGet",
  createOrgProject: "createOrgProjectV1OrgsOrgIdProjectsPost",
  acceptOrgProposal: "acceptOrgProposalV1OrgsOrgIdProjectsProjectIdProposalsProposalIdAcceptPost",
  fundOrgMilestone: "fundOrgMilestoneV1OrgsOrgIdProjectsProjectIdMilestonesMilestoneIdFundPost",
  approveOrgDeliverable: "approveOrgDeliverableV1OrgsOrgIdProjectsProjectIdDeliverablesDeliverableIdApprovePost",
  createOrgDispute: "createOrgDisputeV1OrgsOrgIdProjectsProjectIdDisputesPost",
  listOrgMembers: "listMembersV1OrgsOrgIdMembersGet",
  listOrgTeams: "listTeamsV1OrgsOrgIdTeamsGet",
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
