/**
 * Authenticated application navigation definitions.
 *
 * Centralises link visibility so middleware, layouts, and tests rely on one
 * role-filter contract for UX-only navigation disclosure.
 */

export type AppNavigationLink = {
  href: string;
  label: string;
  roles: string[] | null;
};

/**
 * Shared authenticated navigation links and their role visibility.
 */
export const appLinks: AppNavigationLink[] = [
  { href: "/explore", label: "Explore", roles: null },
  { href: "/projects", label: "Projects", roles: ["operator", "contributor"] },
  { href: "/attestations", label: "Attestations", roles: ["attestor"] },
  { href: "/attestor/assignments", label: "Attestor", roles: ["attestor"] },
  { href: "/dashboard/frameworks", label: "Frameworks", roles: ["contributor"] },
  { href: "/dashboard/collections", label: "Collections", roles: ["contributor"] },
  { href: "/dashboard/financials", label: "Financials", roles: ["contributor"] },
  {
    href: "/dashboard/developer",
    label: "Developer",
    roles: ["contributor", "developer"],
  },
  { href: "/library", label: "Library", roles: ["operator"] },
  { href: "/settings/credentials", label: "Credentials", roles: null },
  { href: "/settings/consent", label: "Consent", roles: null },
  { href: "/settings/notifications", label: "Notifications", roles: null },
  { href: "/settings/saved-searches", label: "Saved Searches", roles: null },
  { href: "/admin/analytics", label: "Admin", roles: ["admin"] },
  { href: "/settings/profile", label: "Settings", roles: null },
];

/**
 * Filter authenticated navigation links for the active role set.
 *
 * @param links - Full navigation link definitions.
 * @param roles - Active roles from the verified session hint.
 */
export function visibleNavLinks(
  links: AppNavigationLink[],
  roles: string[],
): AppNavigationLink[] {
  return links.filter((link) => {
    if (link.roles === null) {
      return true;
    }

    return link.roles.some((role) => roles.includes(role));
  });
}
