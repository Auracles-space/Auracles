/**
 * API base-URL resolution shared by every generated/browser client.
 *
 * The frontend (Amplify) and backend (ECS behind an ALB) answer on different
 * hosts. Auth cookies — notably the `session_hint` the routing middleware
 * reads — are host-only, so a cookie set by the API origin is invisible to the
 * frontend's. To keep auth same-origin we proxy browser traffic through the
 * frontend's own rewrite (`/api/* -> backend`, see next.config.ts) and point
 * `NEXT_PUBLIC_API_URL` at the relative `/api` path.
 *
 * A relative path only resolves in the browser. Server Components fetch from
 * Node, which needs an absolute origin, so on the server we fall back to the
 * direct backend origin (`BACKEND_ORIGIN`).
 */

/** Configured browser API base; relative when proxied through the frontend. */
function configuredApiUrl(): string {
  return process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
}

/**
 * Absolute backend origin used for server-side fetches and WS handshakes.
 *
 * The fallback is localhost deliberately. It was previously the Render origin
 * the platform has since left — a hostname nobody here controls any more, and
 * therefore one somebody else could register and start receiving server-side
 * API traffic on. Localhost cannot be taken over, and a deployed build that
 * reaches for it fails immediately instead of silently talking to a stranger.
 */
function backendOrigin(): string {
  return process.env.BACKEND_ORIGIN ?? "http://localhost:8000";
}

/**
 * Resolve the HTTP API base URL for the current runtime.
 *
 * @returns The relative proxy path in the browser, or an absolute backend
 *   origin on the server when the configured value is a relative proxy path.
 */
export function resolveApiBaseUrl(): string {
  const configured = configuredApiUrl();
  if (typeof window === "undefined" && configured.startsWith("/")) {
    return backendOrigin();
  }
  return configured;
}

/**
 * Resolve the WebSocket URL for realtime channels.
 *
 * WebSocket upgrades are not served through the HTTP rewrite, and the handshake
 * authenticates via a first message (not cookies), so it connects straight to
 * the backend. `NEXT_PUBLIC_WS_URL` sets it explicitly; otherwise it is derived
 * from an absolute API base (local dev).
 *
 * @returns Absolute `ws(s)://.../v1/ws` URL.
 */
export function resolveWebsocketUrl(): string {
  const explicit = process.env.NEXT_PUBLIC_WS_URL;
  if (explicit) {
    return explicit;
  }
  const configured = configuredApiUrl();
  const base = configured.startsWith("http") ? configured : backendOrigin();
  const url = new URL(base);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  url.pathname = "/v1/ws";
  url.search = "";
  return url.toString();
}
