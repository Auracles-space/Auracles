"use client";

/**
 * Project realtime WebSocket hook.
 *
 * The backend uses a first-message auth handshake so access tokens never appear
 * in WebSocket URLs. This hook keeps one Project channel subscribed while a
 * workspace page is mounted and reconnects after transient disconnects.
 */
import { useEffect, useRef, useState } from "react";

import { authTokenStore } from "@/lib/auth/token-store";

type RealtimeEvent = {
  channel?: string;
  event_type?: string;
  payload?: unknown;
  type?: string;
};

type UseProjectRealtimeResult = {
  connected: boolean;
  lastEvent: RealtimeEvent | null;
};

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/**
 * Convert the configured HTTP API URL to the matching WebSocket URL.
 */
function websocketUrl(): string {
  const url = new URL(API_BASE_URL);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  url.pathname = "/v1/ws";
  url.search = "";
  return url.toString();
}

/**
 * Subscribe to realtime updates for one Project workspace.
 *
 * @param projectId - Project channel identifier.
 */
export function useProjectRealtime(projectId: string): UseProjectRealtimeResult {
  const [connected, setConnected] = useState(false);
  const [lastEvent, setLastEvent] = useState<RealtimeEvent | null>(null);
  const retryRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    let cancelled = false;
    let socket: WebSocket | null = null;

    function connect() {
      if (cancelled || typeof window === "undefined") {
        return;
      }

      socket = new WebSocket(websocketUrl());
      socket.addEventListener("open", () => {
        const token = authTokenStore.getState().accessToken;
        socket?.send(JSON.stringify({ token, type: "auth" }));
      });
      socket.addEventListener("message", (message) => {
        const event = JSON.parse(message.data as string) as RealtimeEvent;
        setLastEvent(event);
        if (event.type === "authenticated") {
          socket?.send(
            JSON.stringify({ channel: `project:${projectId}`, type: "subscribe" }),
          );
          setConnected(true);
        }
      });
      socket.addEventListener("close", () => {
        setConnected(false);
        if (!cancelled) {
          retryRef.current = setTimeout(connect, 1500);
        }
      });
    }

    connect();
    return () => {
      cancelled = true;
      setConnected(false);
      if (retryRef.current) {
        clearTimeout(retryRef.current);
      }
      socket?.close();
    };
  }, [projectId]);

  return { connected, lastEvent };
}
