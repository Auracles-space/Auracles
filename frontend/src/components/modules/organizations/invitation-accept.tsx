"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  previewInvitationV1OrgInvitationsTokenGet,
  acceptInvitationV1OrgInvitationsTokenAcceptPost,
  getOrgNda,
  signOrgNda
} from "@/lib/generated/sdk.gen";
import type { OrgInvitationPreviewResponse } from "@/lib/generated/types.gen";
import { getAccessTokenHeaders } from "@/lib/auth/form-client";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import Link from "next/link";

type InvitationAcceptProps = {
  token: string;
};

export function InvitationAccept({ token }: InvitationAcceptProps) {
  const router = useRouter();

  const [preview, setPreview] = useState<OrgInvitationPreviewResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [accepting, setAccepting] = useState(false);
  const [joinedOrg, setJoinedOrg] = useState<{ id: string; name: string } | null>(null);
  const [signingNda, setSigningNda] = useState(false);
  const [ndaSigned, setNdaSigned] = useState(false);
  // Served by the API rather than written here: this screen and the org NDA
  // panel each used to hardcode their own wording, so which door a member came
  // through decided which agreement they signed.
  const [ndaDocument, setNdaDocument] = useState<string | null>(null);

  useEffect(() => {
    async function loadPreview() {
      // First, we check if the user is logged in. If not, we could redirect them,
      // but `previewInvitation` might be a public endpoint so they can see what it is before login.
      // Wait, the plan says: "Auth check: must be logged in. (If not, push to `/login?next=...`)".
      // We will rely on our standard fetch headers. If they are not logged in, we get a 401.
      
      const headers = getAccessTokenHeaders();
      if (!headers.Authorization) {
        // Not logged in -> redirect to login with `next`
        router.push(`/login?next=/org-invitations/${token}`);
        return;
      }

      try {
        const result = await previewInvitationV1OrgInvitationsTokenGet({
          path: { token },
          headers,
        });

        if (result.response.ok && result.data) {
          setPreview(result.data);
        } else {
          setError(result.error?.detail?.error_code || "Invalid or expired invitation.");
        }
      } catch {
        setError("An error occurred loading the invitation.");
      } finally {
        setLoading(false);
      }
    }
    loadPreview();
  }, [token, router]);

  async function handleAccept() {
    setAccepting(true);
    setError(null);

    try {
      const result = await acceptInvitationV1OrgInvitationsTokenAcceptPost({
        path: { token },
        headers: getAccessTokenHeaders(),
      });

      if (!result.response.ok) {
        setError(result.error?.detail?.error_code || "Failed to accept invitation");
        setAccepting(false);
      } else {
        if (result.data?.nda_required) {
          const org = { id: result.data.org.id, name: result.data.org.name };
          setJoinedOrg(org);
          const nda = await getOrgNda({
            path: { org_id: org.id },
            headers: getAccessTokenHeaders(),
          });
          if (nda.response.ok && nda.data) {
            setNdaDocument(nda.data.document);
          }
          setAccepting(false);
        } else {
          router.push("/dashboard/organizations");
        }
      }
    } catch {
      setError("An unexpected error occurred.");
      setAccepting(false);
    }
  }

  async function handleSignNda() {
    if (!joinedOrg) return;
    setSigningNda(true);
    setError(null);
    try {
      const result = await signOrgNda({
        path: { org_id: joinedOrg.id },
        headers: getAccessTokenHeaders(),
      });
      if (!result.response.ok) {
        setError(result.error?.detail?.error_code || "Failed to sign NDA");
        setSigningNda(false);
      } else {
        setNdaSigned(true);
        setTimeout(() => router.push("/dashboard/organizations"), 1500);
      }
    } catch {
      setError("An unexpected error occurred.");
      setSigningNda(false);
    }
  }

  if (loading) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center bg-background p-4">
        <Spinner className="h-8 w-8 text-accent" />
      </div>
    );
  }

  return (
    <div className="flex min-h-[calc(100vh-200px)] flex-col items-center justify-center px-4">
      <div className="w-full max-w-md rounded-2xl border border-border-default bg-surface-1 p-8 text-center shadow-bento">
        {error ? (
          <>
            <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-error/10 text-error">
              <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </div>
            <h1 className="mb-2 font-heading text-2xl font-bold text-foreground">
              Invitation Invalid
            </h1>
            <p className="mb-8 text-sm text-foreground-muted">
              {error}
            </p>
            <Link href="/" className="inline-flex h-10 items-center justify-center rounded-xl bg-surface-2 px-4 py-2 text-sm font-medium text-foreground transition-colors hover:bg-surface-3 w-full">
              Return home
            </Link>
          </>
        ) : joinedOrg ? (
          <>
            <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-2xl bg-surface-2 text-3xl shadow-sm">
              📄
            </div>
            <h1 className="mb-2 font-heading text-2xl font-bold text-foreground">
              {ndaSigned ? "NDA Signed!" : "Sign Non-Disclosure Agreement"}
            </h1>
            
            {ndaSigned ? (
              <p className="mb-6 text-foreground-muted">
                Thank you. Redirecting to your dashboard...
              </p>
            ) : (
              <>
                <p className="mb-4 text-sm text-foreground-muted">
                  You have successfully joined <span className="font-semibold text-foreground">{joinedOrg.name}</span>! 
                  However, you must sign the organization&apos;s NDA before you can participate in any attestations or view confidential materials.
                </p>
                <div className="mb-6 h-32 overflow-y-auto whitespace-pre-wrap rounded-xl border border-border-default bg-surface-2 p-4 text-left text-xs leading-5 text-foreground-muted">
                  {ndaDocument ?? "Loading the agreement…"}
                </div>
                
                <div className="flex flex-col gap-3">
                  {/* Signing text the member was never shown is not consent,
                      so the action waits for the agreement to load. */}
                  <Button
                    onClick={handleSignNda}
                    loading={signingNda}
                    disabled={!ndaDocument}
                    className="w-full min-h-12 text-base"
                  >
                    Sign NDA &amp; Continue
                  </Button>
                  <Button 
                    variant="secondary" 
                    onClick={() => router.push("/dashboard/organizations")} 
                    className="w-full min-h-12 text-base text-foreground-muted"
                  >
                    Skip for now (Limited access)
                  </Button>
                </div>
              </>
            )}
          </>
        ) : preview ? (
          <>
            <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-2xl bg-surface-2 text-3xl shadow-sm">
              🏢
            </div>
            <h1 className="mb-2 font-heading text-2xl font-bold text-foreground">
              You&apos;ve been invited!
            </h1>
            <p className="mb-6 text-foreground-muted">
              You have been invited to join <span className="font-semibold text-foreground">{preview.org_name}</span> as a <span className="font-semibold text-foreground capitalize">{preview.role}</span>.
            </p>
            
            <div className="flex flex-col gap-3">
              <Button onClick={handleAccept} loading={accepting} className="w-full min-h-12 text-base">
                Accept Invitation
              </Button>
              <Link href="/" className="inline-flex items-center justify-center rounded-xl bg-surface-2 px-4 py-2 font-medium text-foreground transition-colors hover:bg-surface-3 w-full min-h-12 text-base">
                Decline & Return Home
              </Link>
            </div>
          </>
        ) : null}
      </div>
    </div>
  );
}
