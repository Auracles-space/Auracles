import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const sdkPath = join(process.cwd(), "src/lib/generated/sdk.gen.ts");
const sdk = readFileSync(sdkPath, "utf8");

if (!sdk.startsWith("// @ts-nocheck")) {
  writeFileSync(sdkPath, `// @ts-nocheck\n${sdk}`);
}
