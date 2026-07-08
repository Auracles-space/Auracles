import { verifySessionHintCookie } from "./src/lib/auth/session-hint-cookie.ts";
import { createHmac } from "node:crypto";

function base64Url(value) {
  return Buffer.from(value)
    .toString("base64")
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

const sessionHintSecret = "auracles-e2e-secret";

function sessionHintValue() {
  const payload = base64Url(
    JSON.stringify(
      {
        exp: Math.floor(Date.now() / 1000) + 900,
        iat: Math.floor(Date.now() / 1000),
        roles: ["contributor", "operator", "attestor", "admin", "platform_admin"],
        totp_verified: true,
        user_id: "00000000-0000-4000-8000-000000000001",
      },
      ["exp", "iat", "roles", "totp_verified", "user_id"],
    ),
  );
  const signature = createHmac("sha256", sessionHintSecret)
    .update(payload)
    .digest("base64url");
  return `${payload}.${signature}`;
}

async function run() {
  const val = sessionHintValue();
  const res = await verifySessionHintCookie(val, sessionHintSecret);
  console.log("verify result:", res);
}
run();
