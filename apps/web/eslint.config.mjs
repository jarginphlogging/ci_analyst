import { defineConfig, globalIgnores } from "eslint/config";

const eslintConfig = defineConfig([
  // Minimal portable config for enterprise mirrors.
  globalIgnores([
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
  ]),
]);

export default eslintConfig;
