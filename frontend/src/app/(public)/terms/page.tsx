/**
 * Public terms of service route.
 *
 * Renders marketplace terms in the shared public document shell so the dense
 * legal body has stable metadata, related links, and readable measure.
 */
import { PublicDocumentShell } from "@/components/modules/legal/public-document-shell";

export const metadata = {
  title: "Terms of Service - Auracles",
  description: "Terms governing access to and use of the Auracles Knowledge Infrastructure Marketplace.",
};

export default function TermsPage() {
  return (
    <PublicDocumentShell
      acknowledgement="By creating an account, accessing, or using Auracles, you acknowledge that you have read, understood, and agreed to these Terms of Service."
      description="Terms governing access to and use of the Auracles Knowledge Infrastructure Marketplace."
      title="Terms of Service"
      updated="June 2026"
      version="1.0"
    >
            <section className="space-y-3">
              <h2 className="font-heading text-xl font-bold text-foreground">1. Introduction</h2>
              <p>Welcome to Auracles.</p>
              <p>
                These Terms of Service (&quot;Terms&quot;) govern access to and use of the Auracles platform, website,
                applications, marketplaces, APIs, and related services (collectively, the &quot;Platform&quot;).
              </p>
              <p>
                Auracles operates a Knowledge Infrastructure Marketplace that enables Contributors to publish, license,
                monetize, and manage professional frameworks while enabling Operators to discover, purchase, license,
                implement, and utilize such frameworks.
              </p>
              <p>
                By creating an account, accessing, or using the Platform, you agree to be bound by these Terms.
                If you do not agree to these Terms, you may not use the Platform.
              </p>
            </section>

            <hr className="border-border-default" />

            <section className="space-y-3">
              <h2 className="font-heading text-xl font-bold text-foreground">2. Definitions</h2>
              <div className="space-y-4 pl-4 border-l-2 border-border-strong">
                <div>
                  <h3 className="font-semibold text-foreground">Auracles</h3>
                  <p className="text-sm mt-1">
                    &quot;Auracles&quot;, &quot;we&quot;, &quot;our&quot;, or &quot;us&quot; refers to Auracles and its affiliates.
                  </p>
                </div>
                <div>
                  <h3 className="font-semibold text-foreground">Contributor</h3>
                  <p className="text-sm mt-1">
                    An individual or organization that creates, uploads, publishes, licenses, sells, or manages frameworks through the Platform.
                  </p>
                </div>
                <div>
                  <h3 className="font-semibold text-foreground">Operator</h3>
                  <p className="text-sm mt-1">
                    An individual or organization that discovers, purchases, licenses, accesses, implements, or otherwise uses frameworks through the Platform.
                  </p>
                </div>
                <div>
                  <h3 className="font-semibold text-foreground">Framework</h3>
                  <p className="text-sm mt-1">
                    A framework includes any operational blueprint, template, methodology, SOP, governance document, compliance program, policy, legal draft, operational playbook, process design, business model, or similar intellectual property made available through the Platform.
                  </p>
                </div>
                <div>
                  <h3 className="font-semibold text-foreground">License</h3>
                  <p className="text-sm mt-1">
                    A permission granted by a Contributor to an Operator allowing the use of a framework under specified conditions.
                  </p>
                </div>
                <div>
                  <h3 className="font-semibold text-foreground">Attestation</h3>
                  <p className="text-sm mt-1">
                    An independent validation, review, verification, certification, or assessment conducted through the Platform.
                  </p>
                </div>
              </div>
            </section>

            <hr className="border-border-default" />

            <section className="space-y-3">
              <h2 className="font-heading text-xl font-bold text-foreground">3. Eligibility</h2>
              <p>To use Auracles, you must:</p>
              <ul className="list-disc pl-5 space-y-1">
                <li>Be at least 18 years old.</li>
                <li>Have legal authority to enter into binding agreements.</li>
                <li>Provide accurate account information.</li>
                <li>Comply with all applicable laws and regulations.</li>
              </ul>
              <p>
                Organizations using Auracles represent that their authorized representatives have authority to act on behalf of the organization.
              </p>
            </section>

            <hr className="border-border-default" />

            <section className="space-y-3">
              <h2 className="font-heading text-xl font-bold text-foreground">4. Account Registration</h2>
              <p>Users must create an account to access certain Platform features.</p>
              <p>Users agree to:</p>
              <ul className="list-disc pl-5 space-y-1">
                <li>Maintain accurate information.</li>
                <li>Keep login credentials secure.</li>
                <li>Promptly update account information.</li>
                <li>Accept responsibility for activities occurring under their account.</li>
              </ul>
              <p>
                Auracles reserves the right to suspend or terminate accounts containing false, misleading, fraudulent, or incomplete information.
              </p>
            </section>

            <hr className="border-border-default" />

            <section className="space-y-3">
              <h2 className="font-heading text-xl font-bold text-foreground">5. Contributor Rights and Responsibilities</h2>
              <p>Contributors may:</p>
              <ul className="list-disc pl-5 space-y-1">
                <li>Upload frameworks.</li>
                <li>Publish framework previews.</li>
                <li>Set framework pricing.</li>
                <li>Define licensing terms.</li>
                <li>Request attestations.</li>
                <li>Receive payments from eligible transactions.</li>
                <li>Update and maintain framework versions.</li>
              </ul>
              <p>Contributors agree that:</p>
              <ul className="list-disc pl-5 space-y-1">
                <li>They own or control the rights necessary to publish submitted frameworks.</li>
                <li>Frameworks do not infringe intellectual property rights of third parties.</li>
                <li>Submitted information is accurate and lawful.</li>
                <li>Frameworks comply with applicable laws and regulations.</li>
              </ul>
              <p>Contributors remain solely responsible for the content they publish.</p>
            </section>

            <hr className="border-border-default" />

            <section className="space-y-3">
              <h2 className="font-heading text-xl font-bold text-foreground">6. Operator Rights and Responsibilities</h2>
              <p>Operators may:</p>
              <ul className="list-disc pl-5 space-y-1">
                <li>Browse frameworks.</li>
                <li>Purchase framework licenses.</li>
                <li>Access purchased frameworks.</li>
                <li>Request attestations.</li>
                <li>Participate in project marketplace activities.</li>
                <li>Submit ratings and reviews.</li>
              </ul>
              <p>Operators agree to:</p>
              <ul className="list-disc pl-5 space-y-1">
                <li>Use frameworks in accordance with purchased licenses.</li>
                <li>Respect intellectual property rights.</li>
                <li>Refrain from unauthorized distribution.</li>
                <li>Provide accurate information.</li>
              </ul>
              <p>Operators may not use purchased frameworks beyond the scope permitted by their license.</p>
            </section>

            <hr className="border-border-default" />

            <section className="space-y-3">
              <h2 className="font-heading text-xl font-bold text-foreground">7. Intellectual Property Ownership</h2>
              <p>
                Auracles does not acquire ownership of framework intellectual property solely because it is published on the Platform.
              </p>
              <p>Unless otherwise agreed:</p>
              <ul className="list-disc pl-5 space-y-1">
                <li>Contributors retain ownership of their frameworks.</li>
                <li>Contributors retain ownership of associated intellectual property.</li>
                <li>Contributors grant Auracles a limited license necessary to operate, display, market, store, and distribute frameworks through the Platform.</li>
              </ul>
              <p>Auracles maintains ownership of:</p>
              <ul className="list-disc pl-5 space-y-1">
                <li>Platform software</li>
                <li>Brand assets</li>
                <li>Marketplace infrastructure</li>
                <li>Reputation systems</li>
                <li>Proprietary algorithms</li>
                <li>Platform content created by Auracles</li>
              </ul>
            </section>

            <hr className="border-border-default" />

            <section className="space-y-3">
              <h2 className="font-heading text-xl font-bold text-foreground">8. Licensing</h2>
              <p>Framework purchases grant Operators a license, not ownership.</p>
              <p>The specific rights granted depend on the selected license type. License categories may include:</p>
              <div className="space-y-3 pl-4 border-l-2 border-border-strong text-sm">
                <p><strong>Personal License:</strong> Single individual usage.</p>
                <p><strong>Team License:</strong> Use by a designated team.</p>
                <p><strong>Organizational License:</strong> Use across a defined organization.</p>
                <p><strong>Enterprise License:</strong> Custom negotiated rights.</p>
              </div>
              <p>Operators may not:</p>
              <ul className="list-disc pl-5 space-y-1">
                <li>Resell frameworks without authorization.</li>
                <li>Redistribute frameworks publicly.</li>
                <li>Remove ownership notices.</li>
                <li>Misrepresent framework ownership.</li>
              </ul>
            </section>

            <hr className="border-border-default" />

            <section className="space-y-3">
              <h2 className="font-heading text-xl font-bold text-foreground">9. Marketplace Transactions</h2>
              <p>Auracles facilitates transactions between Contributors and Operators.</p>
              <p>Auracles is not the direct seller of frameworks unless expressly stated.</p>
              <p>Transaction completion occurs when:</p>
              <ul className="list-disc pl-5 space-y-1">
                <li>Payment is successfully processed.</li>
                <li>Access rights are granted.</li>
                <li>Licensing terms become effective.</li>
              </ul>
              <p>Auracles may collect marketplace commissions and fees.</p>
            </section>

            <hr className="border-border-default" />

            <section className="space-y-3">
              <h2 className="font-heading text-xl font-bold text-foreground">10. Pricing and Payments</h2>
              <p>Contributors determine framework pricing unless otherwise specified.</p>
              <p>Auracles may charge:</p>
              <ul className="list-disc pl-5 space-y-1">
                <li>Marketplace commissions</li>
                <li>Subscription fees</li>
                <li>Attestation fees</li>
                <li>Project marketplace fees</li>
                <li>Enterprise service fees</li>
              </ul>
              <p>All fees are disclosed before purchase. Auracles reserves the right to modify future fees with reasonable notice.</p>
            </section>

            <hr className="border-border-default" />

            <section className="space-y-3">
              <h2 className="font-heading text-xl font-bold text-foreground">11. Payouts to Contributors</h2>
              <p>Contributors may receive earnings from eligible transactions. Payout eligibility may require:</p>
              <ul className="list-disc pl-5 space-y-1">
                <li>Account verification</li>
                <li>Identity verification</li>
                <li>Tax compliance</li>
                <li>Compliance review</li>
              </ul>
              <p>Auracles may delay, withhold, or reverse payouts in cases involving:</p>
              <ul className="list-disc pl-5 space-y-1">
                <li>Fraud</li>
                <li>Chargebacks</li>
                <li>Regulatory obligations</li>
                <li>Intellectual property disputes</li>
                <li>Platform abuse</li>
              </ul>
            </section>

            <hr className="border-border-default" />

            <section className="space-y-3">
              <h2 className="font-heading text-xl font-bold text-foreground">12. Attestation Services</h2>
              <p>Attestations are professional opinions and assessments. Auracles does not guarantee:</p>
              <ul className="list-disc pl-5 space-y-1">
                <li>Accuracy of attestation outcomes.</li>
                <li>Future framework performance.</li>
                <li>Regulatory approval.</li>
                <li>Legal compliance.</li>
              </ul>
              <p>
                Attestation reports should not be considered legal, financial, or professional advice unless expressly provided by a qualified professional.
              </p>
            </section>

            <hr className="border-border-default" />

            <section className="space-y-3">
              <h2 className="font-heading text-xl font-bold text-foreground">13. Reviews and Reputation Systems</h2>
              <p>Users may submit reviews and ratings. Reviews must:</p>
              <ul className="list-disc pl-5 space-y-1">
                <li>Be truthful.</li>
                <li>Be based on actual experience.</li>
                <li>Avoid harassment or abuse.</li>
                <li>Avoid misleading claims.</li>
              </ul>
              <p>Auracles may remove reviews that violate these Terms. Reputation scores are informational and do not constitute endorsements.</p>
            </section>

            <hr className="border-border-default" />

            <section className="space-y-3">
              <h2 className="font-heading text-xl font-bold text-foreground">14. Prohibited Activities</h2>
              <p>Users may not:</p>
              <ul className="list-disc pl-5 space-y-1">
                <li>Commit fraud.</li>
                <li>Misrepresent identity.</li>
                <li>Upload unlawful content.</li>
                <li>Infringe intellectual property rights.</li>
                <li>Circumvent licensing restrictions.</li>
                <li>Interfere with Platform operations.</li>
                <li>Scrape Platform content without authorization.</li>
                <li>Manipulate reviews or reputation systems.</li>
                <li>Use the Platform for illegal activities.</li>
              </ul>
              <p>Violation may result in account suspension or termination.</p>
            </section>

            <hr className="border-border-default" />

            <section className="space-y-3">
              <h2 className="font-heading text-xl font-bold text-foreground">15. Project Marketplace</h2>
              <p>
                The Project Marketplace enables Operators to request custom frameworks and Contributors to submit proposals.
                Auracles acts solely as a marketplace facilitator.
              </p>
              <p>Unless otherwise agreed:</p>
              <ul className="list-disc pl-5 space-y-1">
                <li>Project deliverables remain subject to agreed licensing terms.</li>
                <li>Contributors are responsible for delivery.</li>
                <li>Operators are responsible for project specifications.</li>
              </ul>
              <p>Auracles is not responsible for project outcomes.</p>
            </section>

            <hr className="border-border-default" />

            <section className="space-y-3">
              <h2 className="font-heading text-xl font-bold text-foreground">16. Verification and KYC</h2>
              <p>Auracles may require identity verification and compliance checks. Verification may include:</p>
              <ul className="list-disc pl-5 space-y-1">
                <li>Government identification</li>
                <li>Corporate documentation</li>
                <li>Professional credentials</li>
                <li>Tax information</li>
              </ul>
              <p>Failure to complete verification may limit Platform access.</p>
            </section>

            <hr className="border-border-default" />

            <section className="space-y-3">
              <h2 className="font-heading text-xl font-bold text-foreground">17. Suspension and Termination</h2>
              <p>Auracles may suspend or terminate accounts for:</p>
              <ul className="list-disc pl-5 space-y-1">
                <li>Terms violations</li>
                <li>Fraudulent conduct</li>
                <li>Illegal activity</li>
                <li>Security risks</li>
                <li>Repeated disputes</li>
                <li>Intellectual property violations</li>
              </ul>
              <p>Termination does not eliminate obligations arising before termination.</p>
            </section>

            <hr className="border-border-default" />

            <section className="space-y-3">
              <h2 className="font-heading text-xl font-bold text-foreground">18. Dispute Resolution</h2>
              <p>Auracles may provide dispute resolution services to facilitate fair outcomes. Disputes may involve:</p>
              <ul className="list-disc pl-5 space-y-1">
                <li>Framework ownership</li>
                <li>Licensing violations</li>
                <li>Payment disputes</li>
                <li>Attestation disagreements</li>
                <li>Project marketplace disputes</li>
              </ul>
              <p>
                Auracles reserves discretion regarding dispute resolution procedures. Platform decisions may include account restrictions,
                content removal, refunds, or payment holds.
              </p>
            </section>

            <hr className="border-border-default" />

            <section className="space-y-3">
              <h2 className="font-heading text-xl font-bold text-foreground">19. Disclaimer of Warranties</h2>
              <p>The Platform is provided on an &quot;as is&quot; and &quot;as available&quot; basis. Auracles makes no warranties regarding:</p>
              <ul className="list-disc pl-5 space-y-1">
                <li>Availability, accuracy, reliability, or suitability.</li>
                <li>Performance or commercial outcomes.</li>
              </ul>
              <p>Frameworks are provided by Contributors and remain their responsibility.</p>
            </section>

            <hr className="border-border-default" />

            <section className="space-y-3">
              <h2 className="font-heading text-xl font-bold text-foreground">20. Limitation of Liability</h2>
              <p>To the maximum extent permitted by law, Auracles shall not be liable for:</p>
              <ul className="list-disc pl-5 space-y-1">
                <li>Indirect, consequential, or punitive damages.</li>
                <li>Lost profits, lost revenue, business interruption, or data loss.</li>
                <li>Third-party conduct.</li>
              </ul>
              <p>
                Auracles&apos; aggregate liability shall not exceed the amount paid by the user to Auracles during the twelve (12) months preceding the claim.
              </p>
            </section>

            <hr className="border-border-default" />

            <section className="space-y-3">
              <h2 className="font-heading text-xl font-bold text-foreground">21. Indemnification</h2>
              <p>Users agree to defend, indemnify, and hold harmless Auracles from claims arising from:</p>
              <ul className="list-disc pl-5 space-y-1">
                <li>User content or intellectual property disputes.</li>
                <li>License violations or regulatory violations.</li>
                <li>Breach of these Terms.</li>
              </ul>
            </section>

            <hr className="border-border-default" />

            <section className="space-y-3">
              <h2 className="font-heading text-xl font-bold text-foreground">22. Modifications to the Platform</h2>
              <p>Auracles may add or remove features, modify functionality, update pricing, or change policies. Auracles will provide reasonable notice where appropriate.</p>
            </section>

            <hr className="border-border-default" />

            <section className="space-y-3">
              <h2 className="font-heading text-xl font-bold text-foreground">23. Changes to These Terms</h2>
              <p>
                Auracles may update these Terms periodically. Material changes may be communicated through email, Platform notifications, or website announcements.
                Continued use of the Platform after updates constitutes acceptance of revised Terms.
              </p>
            </section>

            <hr className="border-border-default" />

            <section className="space-y-3">
              <h2 className="font-heading text-xl font-bold text-foreground">24. Governing Law</h2>
              <p>
                These Terms shall be governed by the laws of the jurisdiction in which Auracles is incorporated, without regard to conflict of law principles.
              </p>
            </section>

            <hr className="border-border-default" />

            <section className="space-y-3 border-t-0 bg-surface-2 p-6 rounded-card border border-border-default">
              <h2 className="font-heading text-xl font-bold text-foreground">25. Contact Information</h2>
              <p className="text-sm">Auracles Legal Team</p>
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
