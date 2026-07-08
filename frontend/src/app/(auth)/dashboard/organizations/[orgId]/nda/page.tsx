import { Metadata } from "next";
import { OrgNdaPanel } from "@/components/modules/organizations/org-nda-panel";

export const metadata: Metadata = {
  title: "Organization NDA | Auracles",
};

export default function OrganizationNdaPage() {
  return (
    <div className="space-y-6">
      <p className="text-foreground-muted">
        Review and sign the organization&apos;s Non-Disclosure Agreement.
      </p>
      <OrgNdaPanel />
    </div>
  );
}
