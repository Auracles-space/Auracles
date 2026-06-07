export type SessionHint = {
  userId: string;
  roles: string[];
  totpVerified: boolean;
  expiresAt: number;
};

type BackendSessionHintPayload = {
  user_id: string;
  roles: string[];
  totp_verified: boolean;
  exp: number;
  iat?: number;
};

function base64UrlToBytes(value: string): Uint8Array {
  const normalized = value.replace(/-/g, "+").replace(/_/g, "/");
  const padded = normalized.padEnd(
    normalized.length + ((4 - (normalized.length % 4)) % 4),
    "=",
  );
  const binary = atob(padded);
  return Uint8Array.from(binary, (character) => character.charCodeAt(0));
}

function bytesToBase64Url(bytes: Uint8Array): string {
  const binary = String.fromCharCode(...bytes);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function decodePayload(payload: string): BackendSessionHintPayload {
  const bytes = base64UrlToBytes(payload);
  return JSON.parse(new TextDecoder().decode(bytes)) as BackendSessionHintPayload;
}

async function hmacSha256(payload: string, secret: string): Promise<string> {
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { hash: "SHA-256", name: "HMAC" },
    false,
    ["sign"],
  );
  const signature = await crypto.subtle.sign(
    "HMAC",
    key,
    new TextEncoder().encode(payload),
  );
  return bytesToBase64Url(new Uint8Array(signature));
}

function timingSafeEqual(left: string, right: string): boolean {
  if (left.length !== right.length) {
    return false;
  }
  let result = 0;
  for (let index = 0; index < left.length; index += 1) {
    result |= left.charCodeAt(index) ^ right.charCodeAt(index);
  }
  return result === 0;
}

export async function verifySessionHintCookie(
  cookieValue: string | undefined | null,
  secret: string,
): Promise<SessionHint | null> {
  if (!cookieValue) {
    return null;
  }
  const [payloadSegment, signatureSegment] = cookieValue.split(".");
  if (!payloadSegment || !signatureSegment) {
    return null;
  }
  const expectedSignature = await hmacSha256(payloadSegment, secret);
  if (!timingSafeEqual(expectedSignature, signatureSegment)) {
    return null;
  }

  const payload = decodePayload(payloadSegment);
  if (payload.exp <= Math.floor(Date.now() / 1000)) {
    return null;
  }
  return {
    userId: payload.user_id,
    roles: payload.roles,
    totpVerified: payload.totp_verified,
    expiresAt: payload.exp,
  };
}

export async function signSessionHintForTest(
  payload: BackendSessionHintPayload,
  secret: string,
): Promise<string> {
  const encodedPayload = bytesToBase64Url(
    new TextEncoder().encode(
      JSON.stringify(payload, Object.keys(payload).sort()),
    ),
  );
  return `${encodedPayload}.${await hmacSha256(encodedPayload, secret)}`;
}
