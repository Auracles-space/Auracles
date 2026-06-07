import { defineConfig } from "@hey-api/openapi-ts";

export default defineConfig({
  input: "../contracts/openapi.yaml",
  output: {
    path: "./src/lib/generated",
    format: "prettier",
  },
  client: "@hey-api/client-fetch",
  plugins: ["@hey-api/typescript", "@hey-api/sdk"],
});
