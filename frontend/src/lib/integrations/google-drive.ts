/**
 * Google Drive availability.
 *
 * Drive import is hidden until Google approves the OAuth app. Until then the
 * consent screen shows an unverified-app warning, so every entry point into
 * the flow is a dead end — the Settings connect button most of all, because
 * that is where the warning actually appears.
 *
 * Off unless explicitly switched on, so no environment shows the integration
 * by forgetting to set a variable. Set NEXT_PUBLIC_GOOGLE_DRIVE_ENABLED=true
 * once Google approves; nothing else needs to change.
 *
 * A function rather than a module constant so the value is read per call,
 * which is what lets tests stub the environment.
 */

/**
 * Whether the Google Drive integration should be offered to users.
 *
 * @returns True only when `NEXT_PUBLIC_GOOGLE_DRIVE_ENABLED` is exactly "true".
 */
export function isGoogleDriveEnabled(): boolean {
  return process.env.NEXT_PUBLIC_GOOGLE_DRIVE_ENABLED === "true";
}
