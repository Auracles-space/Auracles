"use client";

/**
 * Connected Accounts settings panel.
 *
 * Lists supported external file providers with the user's connection
 * state, starts the OAuth consent flow, and disconnects with a confirm
 * step. Also renders the outcome banner when the provider callback
 * redirects back with `?connector=...&status=...`.
 */
import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";

import { Button } from "@/components/ui/button";
import {
  connectProviderV1IntegrationsConnectorsProviderConnectPost,
  disconnectProviderV1IntegrationsConnectorsProviderDelete,
  listConnectorsV1IntegrationsConnectorsGet,
} from "@/lib/generated/sdk.gen";
import type { ConnectorStatusItem } from "@/lib/generated/types.gen";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";

/** Human copy for each callback outcome the backend redirects with. */
const CALLBACK_MESSAGES: Record<string, { tone: "ok" | "error"; text: string }> = {
  connected: { tone: "ok", text: "Google Drive connected." },
  denied: { tone: "error", text: "Connection cancelled — access was not granted." },
  error: {
    tone: "error",
    text: "Connecting Google Drive failed. Please try again.",
  },
};

export function IntegrationsList() {
  const searchParams = useSearchParams();
  const [connectors, setConnectors] = useState<ConnectorStatusItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [confirmingDisconnect, setConfirmingDisconnect] = useState<string | null>(
    null,
  );

  const callbackStatus = searchParams.get("status");
  const callbackMessage = callbackStatus
    ? CALLBACK_MESSAGES[callbackStatus] ?? null
    : null;

  const fetchConnectors = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    configureBrowserClient();
    const result = await listConnectorsV1IntegrationsConnectorsGet({
      headers: getAccessTokenHeaders(),
    });
    if (result.response.ok && result.data) {
      setConnectors(result.data.connectors);
    } else {
      setError(describeGeneratedError(result.error));
    }
    setIsLoading(false);
  }, []);

  useEffect(() => {
    void fetchConnectors();
  }, [fetchConnectors]);

  /** Start the consent flow and hand the browser to the provider. */
  async function handleConnect(provider: string) {
    setError(null);
    configureBrowserClient();
    const result = await connectProviderV1IntegrationsConnectorsProviderConnectPost({
      path: { provider },
      headers: getAccessTokenHeaders(),
    });
    if (result.response.ok && result.data?.authorization_url) {
      window.location.assign(result.data.authorization_url);
    } else {
      setError(describeGeneratedError(result.error));
    }
  }

  async function handleDisconnect(provider: string) {
    setError(null);
    configureBrowserClient();
    const result = await disconnectProviderV1IntegrationsConnectorsProviderDelete({
      path: { provider },
      headers: getAccessTokenHeaders(),
    });
    setConfirmingDisconnect(null);
    if (result.response.ok) {
      await fetchConnectors();
    } else {
      setError(describeGeneratedError(result.error));
    }
  }

  if (isLoading) {
    return <p className="p-4 text-sm text-foreground-muted">Loading connections…</p>;
  }

  return (
    <div className="space-y-4">
      {callbackMessage ? (
        <p
          className={
            callbackMessage.tone === "ok"
              ? "rounded-xl border border-border-default bg-surface-2 p-3 text-sm text-accent"
              : "rounded-xl border border-error/30 bg-error/10 p-3 text-sm text-error"
          }
        >
          {callbackMessage.text}
        </p>
      ) : null}
      {error ? <p className="rounded-xl border border-error/30 bg-error/10 p-3 text-sm text-error">{error}</p> : null}
      {connectors.map((connector) => {
        const needsReauth = connector.status === "reauth_required";
        return (
          <div
            key={connector.provider}
            className="flex flex-col gap-3 rounded-xl border border-border-default bg-surface-2 p-4 sm:flex-row sm:items-center sm:justify-between"
          >
            <div className="min-w-0">
              <h3 className="font-semibold text-foreground">Google Drive</h3>
              <p className="text-sm text-foreground-muted">
                Import docs and PDFs directly from your Drive.
              </p>
              {connector.connected && connector.account_email ? (
                <p className="mt-1 text-xs text-accent">
                  Connected as {connector.account_email}
                </p>
              ) : null}
              {needsReauth ? (
                <p className="mt-1 text-xs text-error">
                  Access expired — reconnect to keep importing.
                </p>
              ) : null}
            </div>
            <div className="flex shrink-0 flex-wrap gap-2">
              {!connector.connected || needsReauth ? (
                <Button
                  onClick={() => void handleConnect(connector.provider)}
                  variant="primary"
                >
                  {needsReauth ? "Reconnect" : "Connect"}
                </Button>
              ) : null}
              {connector.connected ? (
                confirmingDisconnect === connector.provider ? (
                  <>
                    <Button
                      onClick={() => void handleDisconnect(connector.provider)}
                      variant="destructive"
                    >
                      Confirm disconnect
                    </Button>
                    <Button
                      onClick={() => setConfirmingDisconnect(null)}
                      variant="secondary"
                    >
                      Keep connected
                    </Button>
                  </>
                ) : (
                  <Button
                    onClick={() => setConfirmingDisconnect(connector.provider)}
                    variant="secondary"
                  >
                    Disconnect
                  </Button>
                )
              ) : null}
            </div>
          </div>
        );
      })}
    </div>
  );
}
