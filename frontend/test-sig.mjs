import { createHmac } from "node:crypto";
const sig = createHmac("sha256", "auracles-e2e-secret").update("foo").digest("base64url");
console.log(sig);
