import { createStore } from "zustand/vanilla";

export type AuthTokenState = {
  accessToken: string | null;
  userId: string | null;
  roles: string[];
  totpVerified: boolean;
  expiresAt: number | null;
};

const initialState: AuthTokenState = {
  accessToken: null,
  userId: null,
  roles: [],
  totpVerified: false,
  expiresAt: null,
};

type JwtPayload = {
  sub: string;
  roles?: string[];
  totp_verified?: boolean;
  exp?: number;
};

export const authTokenStore = createStore<AuthTokenState>(() => initialState);

function decodeBase64UrlJson<T>(encoded: string): T {
  const normalized = encoded.replace(/-/g, "+").replace(/_/g, "/");
  const padded = normalized.padEnd(
    normalized.length + ((4 - (normalized.length % 4)) % 4),
    "=",
  );
  return JSON.parse(atob(padded)) as T;
}

export function setAccessTokenFromJwt(accessToken: string): void {
  const [, payloadSegment] = accessToken.split(".");
  if (!payloadSegment) {
    throw new Error("Invalid JWT payload.");
  }
  const payload = decodeBase64UrlJson<JwtPayload>(payloadSegment);
  authTokenStore.setState({
    accessToken,
    userId: payload.sub,
    roles: payload.roles ?? [],
    totpVerified: payload.totp_verified ?? false,
    expiresAt: payload.exp ?? null,
  });
}

export function clearAuthToken(): void {
  authTokenStore.setState(initialState);
}
