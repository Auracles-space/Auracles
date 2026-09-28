import { FlatCompat } from "@eslint/eslintrc";
import { dirname } from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const compat = new FlatCompat({
  baseDirectory: __dirname,
});

const eslintConfig = [
  ...compat.extends("next/core-web-vitals", "next/typescript"),
  {
    ignores: [
      ".next/**",
      "node_modules/**",
      "coverage/**",
      "next-env.d.ts",
      "src/lib/generated/sdk.gen.ts",
    ],
  },
  {
    // Not in next/core-web-vitals or next/typescript, and its absence let a
    // line sit stranded after a `return` in an E2E spec: the session mock on
    // that line never ran, so the test redirected to /login and burned its full
    // timeout on every run. `error`, not `warn` — `pnpm lint` in CI only fails
    // on errors, so a warning here would be as invisible as no rule at all.
    rules: { "no-unreachable": "error" },
  },
];

export default eslintConfig;
