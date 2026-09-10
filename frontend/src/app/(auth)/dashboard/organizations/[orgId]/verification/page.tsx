import { OrgVerificationPanel } from "@/components/modules/organizations/org-verification-panel";

/**
 * Organization business-verification (KYB) page.
 *
 * The surface `org_kyb_required` sends an org admin to when a capability is
 * blocked, so its path must stay in step with that error's onboarding_url.
 */
export default function OrgVerificationPage() {
  return <OrgVerificationPanel />;
}
