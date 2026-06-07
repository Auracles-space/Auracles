import {
  client,
  refreshToken as generatedRefreshToken,
} from "@/lib/generated/sdk.gen";

import { clearAuthToken, setAccessTokenFromJwt } from "./token-store";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function refreshAccessToken(): Promise<boolean> {
  client.setConfig({
    baseUrl: API_BASE_URL,
    credentials: "include",
    cache: "no-store",
  });

  const result = await generatedRefreshToken();
  if (!result.response.ok || !result.data?.access_token) {
    clearAuthToken();
    return false;
  }

  setAccessTokenFromJwt(result.data.access_token);
  return true;
}
