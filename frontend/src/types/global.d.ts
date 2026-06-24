// Ambient declarations for non-code side-effect imports.
//
// Next.js generates a `*.css` module declaration into `.next/types` only after
// a build/dev run, so a fresh checkout trips ts(2882) on `import "./globals.css"`
// until that directory exists. Declaring it here keeps the editor and a clean
// `tsc` in agreement regardless of build state.
declare module "*.css";
