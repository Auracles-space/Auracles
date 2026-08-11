/**
 * Public data security policy route.
 *
 * Renders security obligations and platform controls in the shared public
 * document shell without changing the policy text.
 */
import { PublicDocumentShell } from "@/components/modules/legal/public-document-shell";

export const metadata = {
  title: "Data Security Policy - Auracles",
  description: "Security principles, access controls, encryption standards, and governance policies enforced by Auracles.",
};

export default function SecurityPage() {
  return (
    <PublicDocumentShell
      acknowledgement="By creating an account, accessing, or using Auracles, Contributors and Operators acknowledge that they have read, understood, and agreed to comply with this Data Security Policy and the security obligations described herein."
      description="Security principles, access controls, encryption standards, and governance policies enforced by Auracles."
      title="Data Security Policy"
      updated="June 2026"
      version="1.0"
    >
            <section className="space-y-3">
              <h2 className="font-heading text-xl font-bold text-foreground">1. Purpose</h2>
              <p>
                The purpose of this Data Security Policy is to establish the principles, controls, responsibilities, and procedures
                used by Auracles to protect the confidentiality, integrity, availability, and lawful processing of information
                stored, transmitted, and managed through the Auracles platform.
              </p>
              <p>
                This policy applies to all Contributors, Operators, employees, contractors, service providers, partners, and
                authorized users of the Auracles platform.
              </p>
              <p>
                Auracles recognizes that trust is fundamental to the exchange of operational knowledge and intellectual property and is
                committed to maintaining appropriate security standards across its systems and operations.
              </p>
            </section>

            <hr className="border-border-default" />

            <section className="space-y-3">
              <h2 className="font-heading text-xl font-bold text-foreground">2. Scope</h2>
              <p>This policy applies to all information processed through Auracles, including:</p>
              <div className="space-y-4 pl-4 border-l-2 border-border-strong text-sm">
                <div>
                  <h3 className="font-semibold text-foreground">User Information</h3>
                  <p className="mt-0.5">Account Information, Identity Verification Information, Contact Information, Professional Credentials.</p>
                </div>
                <div>
                  <h3 className="font-semibold text-foreground">Marketplace Information</h3>
                  <p className="mt-0.5">Framework Metadata, Framework Content, Licensing Records, Ownership Records, Version Histories.</p>
                </div>
                <div>
                  <h3 className="font-semibold text-foreground">Financial Information</h3>
                  <p className="mt-0.5">Transaction Records, Billing Information, Payout Information, Subscription Information.</p>
                </div>
                <div>
                  <h3 className="font-semibold text-foreground">Trust and Reputation Information</h3>
                  <p className="mt-0.5">Reviews, Ratings, Attestations, Verification Status, Reputation Scores.</p>
                </div>
                <div>
                  <h3 className="font-semibold text-foreground">Operational Information</h3>
                  <p className="mt-0.5">Activity Logs, Security Logs, Platform Analytics, Support Communications.</p>
                </div>
              </div>
            </section>

            <hr className="border-border-default" />

            <section className="space-y-3">
              <h2 className="font-heading text-xl font-bold text-foreground">3. Security Principles</h2>
              <p>Auracles operates according to the following security principles:</p>
              <div className="grid gap-4 sm:grid-cols-2 text-sm mt-4">
                <div className="rounded-xl border border-border-default p-4 bg-surface-1">
                  <h3 className="font-bold text-foreground">Confidentiality</h3>
                  <p className="mt-1 text-foreground-muted">Information shall only be accessible to authorized individuals.</p>
                </div>
                <div className="rounded-xl border border-border-default p-4 bg-surface-1">
                  <h3 className="font-bold text-foreground">Integrity</h3>
                  <p className="mt-1 text-foreground-muted">Information shall remain accurate, complete, and protected from unauthorized modification.</p>
                </div>
                <div className="rounded-xl border border-border-default p-4 bg-surface-1">
                  <h3 className="font-bold text-foreground">Availability</h3>
                  <p className="mt-1 text-foreground-muted">Systems and information shall remain accessible to authorized users when required.</p>
                </div>
                <div className="rounded-xl border border-border-default p-4 bg-surface-1">
                  <h3 className="font-bold text-foreground">Least Privilege</h3>
                  <p className="mt-1 text-foreground-muted">Users and personnel receive only the minimum level of access required to perform authorized activities.</p>
                </div>
              </div>
              <p className="text-sm mt-2">
                <strong>Accountability:</strong> Actions performed within the platform shall be traceable through logging and audit controls.
              </p>
              <p className="text-sm">
                <strong>Security by Design:</strong> Security considerations shall be integrated into product design, development, deployment, and operational processes.
              </p>
            </section>

            <hr className="border-border-default" />

            <section className="space-y-3">
              <h2 className="font-heading text-xl font-bold text-foreground">4. Data Classification</h2>
              <p>Auracles classifies information according to sensitivity levels:</p>
              <ul className="list-disc pl-5 space-y-2">
                <li>
                  <strong>Public Data:</strong> Information intentionally made publicly available.
                  <span className="block text-xs mt-0.5 text-foreground-subtle">Examples: Public Profiles, Framework Listings, Marketplace Reviews, Public Reputation Scores.</span>
                </li>
                <li>
                  <strong>Internal Data:</strong> Information intended for platform operations.
                  <span className="block text-xs mt-0.5 text-foreground-subtle">Examples: Internal Analytics, Operational Metrics, Support Records.</span>
                </li>
                <li>
                  <strong>Confidential Data:</strong> Information requiring restricted access.
                  <span className="block text-xs mt-0.5 text-foreground-subtle">Examples: Purchased Framework Content, Private Communications, Transaction Information, Business Information.</span>
                </li>
                <li>
                  <strong>Restricted Data:</strong> Highly sensitive information requiring enhanced protection.
                  <span className="block text-xs mt-0.5 text-foreground-subtle">Examples: Identity Verification Records, Government Identification, Financial Account Information, Authentication Credentials, Security Logs.</span>
                </li>
              </ul>
            </section>

            <hr className="border-border-default" />

            <section className="space-y-3">
              <h2 className="font-heading text-xl font-bold text-foreground">5. Access Control</h2>
              <p>Auracles implements role-based access controls. Access to information is granted based on:</p>
              <ul className="list-disc pl-5 space-y-1">
                <li>User Role</li>
                <li>Business Need</li>
                <li>Security Requirements</li>
                <li>Regulatory Obligations</li>
              </ul>
              <div className="mt-4 space-y-3 text-sm pl-4 border-l-2 border-border-strong">
                <p>
                  <strong>Contributor Access Rights:</strong> Contributors may access their own account information, frameworks, licensing records, financial records, and reputation info. They may not access other users&apos; private data or internal platform systems.
                </p>
                <p>
                  <strong>Operator Access Rights:</strong> Operators may access their own account, purchased frameworks, transaction logs, licensing records, and reputation. They may not access contributor details beyond what is disclosed via transactions.
                </p>
                <p>
                  <strong>Administrative Access:</strong> Administrative access is restricted to authorized personnel and granted only when necessary for security operations, compliance, support, or platform maintenance. Administrative actions are logged and audited.
                </p>
              </div>
            </section>

            <hr className="border-border-default" />

            <section className="space-y-3">
              <h2 className="font-heading text-xl font-bold text-foreground">6. Authentication and Account Security</h2>
              <p>Auracles requires secure authentication measures. Users are responsible for:</p>
              <ul className="list-disc pl-5 space-y-1">
                <li>Maintaining password confidentiality.</li>
                <li>Protecting authentication devices.</li>
                <li>Reporting suspected compromises.</li>
                <li>Updating credentials when necessary.</li>
              </ul>
              <p>Auracles may require Multi-Factor Authentication (MFA), password rotation, risk-based authentication, and identity verification.</p>
            </section>

            <hr className="border-border-default" />

            <section className="space-y-3">
              <h2 className="font-heading text-xl font-bold text-foreground">7. Encryption Standards</h2>
              <p>Auracles employs encryption to protect information:</p>
              <ul className="list-disc pl-5 space-y-1">
                <li>
                  <strong>Data in Transit:</strong> Information transmitted between users and the platform shall be encrypted using secure transport protocols (TLS, HTTPS).
                </li>
                <li>
                  <strong>Data at Rest:</strong> Sensitive information stored by Auracles shall be encrypted where appropriate (Identity Verification Records, Financial Information, Credentials, Security Logs).
                </li>
              </ul>
            </section>

            <hr className="border-border-default" />

            <section className="space-y-3">
              <h2 className="font-heading text-xl font-bold text-foreground">8. Intellectual Property Protection</h2>
              <p>
                Auracles recognizes the importance of protecting framework intellectual property. Security controls include access restrictions,
                license enforcement, watermarking, download controls, activity monitoring, ownership tracking, and provenance records.
                Unauthorized copying, redistribution, or misuse of frameworks is prohibited.
              </p>
            </section>

            <hr className="border-border-default" />

            <section className="space-y-3">
              <h2 className="font-heading text-xl font-bold text-foreground">9. Monitoring and Logging</h2>
              <p>
                Auracles maintains logs for security and operational purposes (login events, access events, transaction activity, licensing activity,
                administrative actions, and security events). Logs are retained for security, legal, and compliance purposes.
              </p>
            </section>

            <hr className="border-border-default" />

            <section className="space-y-3">
              <h2 className="font-heading text-xl font-bold text-foreground">10. Vulnerability Management</h2>
              <p>
                Auracles regularly evaluates systems for vulnerabilities through security reviews, penetration testing, vulnerability scanning,
                risk assessments, and infrastructure audits. Identified vulnerabilities are prioritized and remediated according to risk.
              </p>
            </section>

            <hr className="border-border-default" />

            <section className="space-y-3">
              <h2 className="font-heading text-xl font-bold text-foreground">11. Incident Response</h2>
              <p>
                Auracles maintains procedures for responding to security incidents (unauthorized access, data exposure, credential theft,
                malware, service disruption, and intellectual property misuse).
              </p>
              <div className="grid gap-2 grid-cols-3 sm:grid-cols-6 text-xs text-center mt-3 font-semibold uppercase tracking-wider">
                <div className="p-2 border border-border-default rounded-lg bg-surface-1">1. Detect</div>
                <div className="p-2 border border-border-default rounded-lg bg-surface-1">2. Contain</div>
                <div className="p-2 border border-border-default rounded-lg bg-surface-1">3. Investigate</div>
                <div className="p-2 border border-border-default rounded-lg bg-surface-1">4. Remediate</div>
                <div className="p-2 border border-border-default rounded-lg bg-surface-1">5. Recover</div>
                <div className="p-2 border border-border-default rounded-lg bg-surface-1">6. Review</div>
              </div>
            </section>

            <hr className="border-border-default" />

            <section className="space-y-3">
              <h2 className="font-heading text-xl font-bold text-foreground">12. Breach Notification</h2>
              <p>
                Where required by applicable law, Auracles will notify affected users regarding security incidents involving personal information.
                Notifications may cover the nature of the incident, information affected, actions taken, and recommended user actions.
              </p>
            </section>

            <hr className="border-border-default" />

            <section className="space-y-3">
              <h2 className="font-heading text-xl font-bold text-foreground">13. Third-Party Service Providers</h2>
              <p>
                Auracles may engage trusted third-party providers for cloud infrastructure, identity verification, payment processing,
                monitoring, analytics, and customer support. Third-party providers must meet appropriate security standards.
              </p>
            </section>

            <hr className="border-border-default" />

            <section className="space-y-3">
              <h2 className="font-heading text-xl font-bold text-foreground">14. Data Retention and Disposal</h2>
              <p>
                Information is retained only as long as necessary for platform operations, licensing records, ownership tracking, legal obligations,
                and security purposes. When no longer required, data is deleted, archived, or anonymized. Framework provenance records may be
                retained indefinitely to preserve ownership and licensing history.
              </p>
            </section>

            <hr className="border-border-default" />

            <section className="space-y-3">
              <h2 className="font-heading text-xl font-bold text-foreground">15. User Security Responsibilities</h2>
              <p>Contributors and Operators share responsibility for maintaining platform security. Users agree to:</p>
              <ul className="list-disc pl-5 space-y-1">
                <li><strong>Protect Credentials:</strong> Do not share passwords or authentication devices.</li>
                <li><strong>Secure Devices:</strong> Maintain secure devices used to access Auracles.</li>
                <li><strong>Report Security Concerns:</strong> Promptly report suspicious activity.</li>
                <li><strong>Respect Access Rights:</strong> Do not attempt to access unauthorized information.</li>
                <li><strong>Protect Purchased Content:</strong> Store frameworks securely and comply with licensing restrictions.</li>
              </ul>
            </section>

            <hr className="border-border-default" />

            <section className="space-y-3">
              <h2 className="font-heading text-xl font-bold text-foreground">16. Prohibited Security Activities</h2>
              <p>
                Users may not attempt unauthorized access, circumvent security controls, reverse engineer platform systems, distribute malware,
                interfere with operations, exploit vulnerabilities, access another user&apos;s account, or use unauthorized automated tools.
                Violations may result in account suspension, termination, legal action, or referral to law enforcement.
              </p>
            </section>

            <hr className="border-border-default" />

            <section className="space-y-3">
              <h2 className="font-heading text-xl font-bold text-foreground">17. Business Continuity and Disaster Recovery</h2>
              <p>
                Auracles maintains measures intended to support platform resilience and operational continuity, including data backups,
                redundant infrastructure, recovery procedures, and operational monitoring.
              </p>
            </section>

            <hr className="border-border-default" />

            <section className="space-y-3">
              <h2 className="font-heading text-xl font-bold text-foreground">18. Security Governance</h2>
              <p>
                Security oversight is managed by Auracles management and authorized personnel. Oversight activities include policy enforcement,
                risk management, security reviews, compliance monitoring, and incident oversight.
              </p>
            </section>

            <hr className="border-border-default" />

            <section className="space-y-3">
              <h2 className="font-heading text-xl font-bold text-foreground">19. Compliance</h2>
              <p>
                Auracles seeks to align its security practices with recognized industry principles and applicable legal requirements, including
                data protection regulations, privacy requirements, contractual obligations, and enterprise security standards.
              </p>
            </section>

            <hr className="border-border-default" />

            <section className="space-y-3">
              <h2 className="font-heading text-xl font-bold text-foreground">20. Changes to This Policy</h2>
              <p>
                Auracles may update this Data Security Policy periodically. Material updates will be communicated through platform notifications,
                email communications, or website announcements. Continued use of the platform constitutes acceptance of revised policies.
              </p>
            </section>

            <hr className="border-border-default" />

            <section className="space-y-3 border-t-0 bg-surface-2 p-6 rounded-card border border-border-default">
              <h2 className="font-heading text-xl font-bold text-foreground">21. Contact Information</h2>
              <p className="text-sm">Auracles Security Team</p>
              <p className="text-sm mt-1">
                Email:{" "}
                <a href="mailto:admin@auracles.space" className="text-accent hover:underline font-semibold">
                  admin@auracles.space
                </a>
              </p>
              <p className="text-sm mt-0.5">
                Website:{" "}
                <a href="https://www.auracles.space" target="_blank" rel="noopener noreferrer" className="text-accent hover:underline">
                  https://www.auracles.space
                </a>
              </p>
            </section>
    </PublicDocumentShell>
  );
}
