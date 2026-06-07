/**
 * Authenticated account settings route.
 *
 * Hosts email-change and deactivation controls backed by Slice 11 settings
 * endpoints.
 */
import { AuthPageShell } from "@/components/modules/auth/auth-page-shell";
import { AccountSettingsPanel } from "@/components/modules/settings/account-settings-panel";

export default function AccountSettingsPage() {
  return (
    <AuthPageShell
      eyebrow="Account settings"
      summary="Change your verified email address or deactivate the account after backend confirmation checks."
      title="Control account identity and access."
    >
      <AccountSettingsPanel />
    </AuthPageShell>
  );
}
