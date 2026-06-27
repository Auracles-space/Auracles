"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ProfileEditor } from "@/components/modules/profiles/profile-editor";
import { loadCurrentUserSession } from "@/lib/auth/current-user-session";

/**
 * Dedicated client-side profile editor route.
 *
 * Checks authentication status and mounts the ProfileEditor.
 * Redirects unauthenticated attempts back to the sign-in flow.
 */
export default function ProfileEditPage() {
  const router = useRouter();
  const [checking, setChecking] = useState(true);

  useEffect(() => {
    let active = true;
    async function checkAuth() {
      const user = await loadCurrentUserSession();
      if (!active) return;
      if (!user) {
        router.replace("/login?next=/profile/edit");
      } else {
        setChecking(false);
      }
    }
    void checkAuth();
    return () => {
      active = false;
    };
  }, [router]);

  if (checking) {
    return (
      <main className="px-4 py-8 text-foreground md:px-8">
        <p className="mx-auto max-w-[1280px] text-sm text-foreground-muted">
          Loading editor...
        </p>
      </main>
    );
  }

  return (
    <main className="px-4 py-8 text-foreground md:px-8">
      <div className="mx-auto max-w-3xl">
        <div className="mb-6 flex items-center justify-between">
          <h1 className="font-heading text-2xl font-bold text-foreground">
            Edit your profile
          </h1>
          <span className="text-xs font-semibold uppercase tracking-[0.05em] text-foreground-subtle">
            Editing
          </span>
        </div>
        <ProfileEditor
          onSaved={() => router.push("/profile/me")}
          onCancel={() => router.push("/profile/me")}
        />
      </div>
    </main>
  );
}
